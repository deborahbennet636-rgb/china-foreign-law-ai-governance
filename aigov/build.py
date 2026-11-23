"""Assemble the published dataset and the single-file viewer.

Nothing here decides anything about the law. The build copies validated
records, attaches the verification level computed from their sources, and
counts what is there, so that every number shown to a reader can be
recomputed from the data.
"""
import base64
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import PATHS, SCHEMA_VERSION
from .checks_case import sources_of_case
from .checks_obligation import effective_duty
from .evidence import SnapshotIndex, assess
from .store import Database, Record

DATA_MARK = "/*__DATA__*/"
STYLE_MARK = "/*__STYLE__*/"
SCRIPT_MARK = "/*__SCRIPT__*/"
SCRIPT_FILES = ("labels.js", "dom.js", "app.js")
STYLE_HASH_MARK = "__STYLE_HASH__"
SCRIPT_HASH_MARK = "__SCRIPT_HASH__"
SOURCE_FIELDS = ("id", "url", "publisher", "kind", "official", "fetched_at", "sha256", "bytes", "note")
REFERENCE_FILE = PATHS.data / "reference" / "agora-coverage.json"


def _count(values: List[Any]) -> Dict[str, int]:
    """Count values, most common first."""
    return dict(Counter(str(value) for value in values).most_common())


def compute_stats(instruments: List[Record], cases: List[Record], database: Database) -> Dict[str, Any]:
    """Count the records of the database.

    Args:
        instruments: Instrument records with verification attached.
        cases: Case records with verification attached.
        database: The loaded database.

    Returns:
        Counts by jurisdiction, verification level and anchor basis.
    """
    anchors = [anchor for case in cases for anchor in case.get("legal_anchors", [])]
    return {
        "instruments": len(instruments),
        "instruments_by_jurisdiction": _count([item["jurisdiction"] for item in instruments]),
        "instruments_complete": sum(1 for item in instruments if item.get("complete")),
        "provisions": sum(len(item["provisions"]) for item in instruments),
        "cases": len(cases),
        "cases_by_jurisdiction": _count([item["jurisdiction"] for item in cases]),
        "cases_by_verification": _count([item["verification"] for item in cases]),
        "cases_with_case_number": sum(1 for item in cases if item.get("case_numbers")),
        "cases_final": sum(1 for item in cases if item.get("is_final") is True),
        "cases_with_judgment": sum(
            1 for item in cases if any(database.manifest[source]["kind"] == "JUDGMENT" for source in item.get("scopes", {}))
        ),
        "cases_with_editorial_link": sum(1 for item in cases if item.get("scope_links")),
        "anchors": len(anchors),
        "anchors_by_basis": _count([anchor["basis"] for anchor in anchors]),
        "cases_without_anchor": sum(1 for item in cases if not item.get("legal_anchors")),
        "issues": len(database.issues),
        "leads_open": sum(1 for item in database.leads if item.get("status") == "OPEN"),
        "sources": len(database.manifest),
        "sources_official": sum(1 for entry in database.manifest.values() if entry["official"]),
        # v1 layers. Counted here rather than typed on a page, so that the
        # figure a reader sees can be recomputed from the data.
        "instruments_by_foreign_related": _count([item.get("foreign_related", "UNKNOWN") for item in instruments]),
        "obligations": len(database.obligations),
        "obligations_by_kind": _count([item.get("kind", "") for item in database.obligations]),
        "obligations_by_modality": _count([item.get("modality", "") for item in database.obligations]),
        "obligations_extraterritorial": sum(1 for item in database.obligations if item.get("extraterritorial")),
        "countermeasures": len(database.countermeasures),
        "countermeasures_by_direction": _count([item.get("direction", "") for item in database.countermeasures]),
        "arguments_cases": len(database.arguments),
        "arguments_sentences": sum(len(item.get("sentences", [])) for item in database.arguments),
        "arguments_by_role": _count(
            [sent.get("role", "") for item in database.arguments for sent in item.get("sentences", [])]
        ),
        "arguments_by_mode": _count([item.get("annotation_mode", "") for item in database.arguments]),
    }


def _load_reference() -> Optional[Dict[str, Any]]:
    """Return the measured AGORA coverage figures, without the document list."""
    if not REFERENCE_FILE.exists():
        return None
    figures = json.loads(REFERENCE_FILE.read_text(encoding="utf-8"))
    figures.pop("china_list", None)
    return figures


def build_dataset(database: Database, index: Optional[SnapshotIndex] = None,
                  built_at: Optional[str] = None) -> Dict[str, Any]:
    """Build the dataset that is published and embedded in the viewer.

    The caller must have validated ``database`` first.

    Args:
        database: The loaded, validated database.
        index: Snapshot index; defaults to one over the database manifest.
        built_at: Build date as ``YYYY-MM-DD``; defaults to today.

    Returns:
        The dataset as a JSON-serialisable mapping.
    """
    index = index or SnapshotIndex(database.manifest)
    # Which instrument is amended by which is computed, never typed, so the
    # link always rests on the amending act's own evidence.
    amended_by: Dict[str, List[str]] = {}
    for record in database.instruments:
        for target in record.get("amends", []):
            amended_by.setdefault(target, []).append(record["id"])
    instruments = [
        {**record, "amended_by": amended_by.get(record["id"], []), **assess(record["source_ids"], index)}
        for record in database.instruments
    ]
    cases = [{**record, **assess(sources_of_case(record), index)} for record in database.cases]
    sources = [
        {field: entry[field] for field in SOURCE_FIELDS if field in entry}
        for entry in database.manifest.values()
    ]
    # An obligation can never be more certain than the provision it reads, so
    # it inherits that instrument's level instead of carrying one of its own.
    level_by_instrument = {item["id"]: item.get("verification", "PENDING") for item in instruments}
    obligations = [
        {
            **record,
            "verification": level_by_instrument.get(record.get("instrument_id"), "PENDING"),
            "duty_text": effective_duty(record),
        }
        for record in database.obligations
    ]
    case_meta = {
        item["id"]: {
            "verification": item.get("verification", "PENDING"),
            "evidence_grade": item.get("evidence_grade", "-"),
        }
        for item in cases
    }
    arguments = [
        {**record, **case_meta.get(record.get("case_id", ""), {"verification": "PENDING", "evidence_grade": "-"})}
        for record in database.arguments
    ]
    return {
        "schema": SCHEMA_VERSION,
        "built_at": built_at or date.today().isoformat(),
        "stats": compute_stats(instruments, cases, database),
        "reference": {"agora": _load_reference()},
        "sources": sources,
        "instruments": instruments,
        "cases": cases,
        "issues": database.issues,
        "leads": database.leads,
        "obligations": obligations,
        "countermeasures": [
            {**record, **assess(record.get("source_ids", []), index)} for record in database.countermeasures
        ],
        "arguments": arguments,
    }


def embed_json(dataset: Dict[str, Any]) -> str:
    """Serialise the dataset so it is safe inside a ``<script>`` element.

    ``<`` is written as an escape so that no text in the data, such as a
    quoted ``</script>``, can end the element early.
    """
    return json.dumps(dataset, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def render_page(dataset: Dict[str, Any], web_dir: Path = PATHS.web) -> str:
    """Inline the style, the script and the data into the page template.

    Args:
        dataset: Output of ``build_dataset``.
        web_dir: Directory holding ``template.html``, ``style.css`` and
            the script files.

    Returns:
        The complete single-file page.

    Raises:
        ValueError: When the template lacks one of the three marks.
    """
    page = (web_dir / "template.html").read_text(encoding="utf-8")
    script = "\n".join((web_dir / name).read_text(encoding="utf-8") for name in SCRIPT_FILES)
    parts = {
        STYLE_MARK: (web_dir / "style.css").read_text(encoding="utf-8"),
        SCRIPT_MARK: script,
        DATA_MARK: embed_json(dataset),
    }
    # The page allows exactly these two inline blocks and nothing else. The
    # hash covers what stands between the tags, including the line breaks.
    hashes = {STYLE_HASH_MARK: _csp_hash(page, "style", STYLE_MARK, parts[STYLE_MARK]),
              SCRIPT_HASH_MARK: _csp_hash(page, "script", SCRIPT_MARK, parts[SCRIPT_MARK])}
    for mark, content in {**hashes, **parts}.items():
        if page.count(mark) != 1:
            raise ValueError(f"template must contain {mark} exactly once")
        page = page.replace(mark, content)
    return page


def _csp_hash(template: str, tag: str, mark: str, content: str) -> str:
    """Return the Content-Security-Policy hash of one inline block.

    Raises:
        ValueError: When the template does not hold the block in the
            expected form, so the hash could not be trusted.
    """
    if f"<{tag}>\n{mark}\n</{tag}>" not in template:
        raise ValueError(f"template must contain <{tag}> with {mark} alone on its own line")
    digest = hashlib.sha256(f"\n{content}\n".encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")
