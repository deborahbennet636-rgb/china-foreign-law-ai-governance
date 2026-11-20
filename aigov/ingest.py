"""Build instrument and case records from ingest specs and snapshots.

Records under ``data/instruments`` and ``data/cases`` are never written by
hand. They are produced here, and the validator produces them again and
compares, so a stored record cannot drift from its spec and its snapshot.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .caseparse import clean_lines, extract_block, split_sections
from .config import PATHS
from .evidence import SnapshotIndex
from .splitter import check_consecutive, check_sequence, get_splitter, select_provisions, slice_lines

Record = Dict[str, Any]

METADATA_ONLY = "metadata-only"
PART_KEYS = ("source_id", "start_at", "end_before", "select")
CASE_LIST_FIELDS = ("case_numbers", "ai_roles", "issues", "legal_anchors", "history", "also_reported_in")


def spec_ref(path: Path) -> str:
    """Return the path of a spec relative to the project, as stored in records."""
    return path.resolve().relative_to(PATHS.root).as_posix()


def load_spec(path: Path) -> Dict[str, Any]:
    """Read one ingest spec."""
    return json.loads(path.read_text(encoding="utf-8"))


def _parts_of(spec: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Return the source parts of an instrument spec.

    A long statute may be published over several pages. Such a spec lists
    them under ``parts``; an ordinary spec is a single part.
    """
    if "parts" in spec:
        return [dict(part) for part in spec["parts"]]
    return [{key: spec[key] for key in PART_KEYS if key in spec}]


def build_instrument(spec: Mapping[str, Any], generated_by: str, index: SnapshotIndex) -> Record:
    """Build one instrument record.

    Args:
        spec: The ingest spec.
        generated_by: Project-relative path of the spec.
        index: Snapshot index used to read the source text.

    Returns:
        The instrument record. Each provision names the snapshot it was
        cut from.

    Raises:
        KeyError: When the spec names an unknown snapshot or splitter.
        ValueError: When markers are missing or numbering is broken.
    """
    parts = _parts_of(spec)
    complete = False
    provisions: List[Record] = []
    for part in parts:
        source_id = part["source_id"]
        index.entry(source_id)
        if spec["format"] == METADATA_ONLY:
            continue
        lines = slice_lines(index.text(source_id), part.get("start_at"), part.get("end_before"))
        found = get_splitter(spec["format"])(lines)
        if "select" in part:
            check_consecutive(found)
            found = select_provisions(found, part["select"])
        else:
            check_sequence(found, spec["expected_provisions"])
            complete = len(parts) == 1
        provisions += [{**item, "source_id": source_id} for item in found]

    record: Record = dict(spec["record"])
    record["source_id"] = parts[0]["source_id"]
    record["source_ids"] = [part["source_id"] for part in parts]
    record["complete"] = complete
    record["expected_provisions"] = spec.get("expected_provisions")
    record["meta_evidence"] = dict(spec.get("meta_evidence", {}))
    record["derived_dates"] = dict(spec.get("derived_dates", {}))
    record["generated_by"] = generated_by
    record["provisions"] = provisions
    return record


def _digest_parts(digest: Mapping[str, Any], index: SnapshotIndex) -> Record:
    """Copy the title and sections of one digest block out of its snapshot."""
    source_id = digest["source_id"]
    lines = clean_lines(index.text(source_id))
    block = extract_block(lines, digest["block_start"], digest["block_end"])
    title, sections = split_sections(block, digest["sections"], digest.get("stop", ()))
    excerpts = [
        {"kind": kind, "text": "\n".join(sections[kind]), "source_id": source_id}
        for kind in digest["sections"]
    ]
    headline = " ".join(part for part in (title[0] if title else "", "".join(title[1:])) if part)
    return {"source_title": {"text": headline, "source_id": source_id}, "excerpts": excerpts}


def build_case(case_spec: Mapping[str, Any], defaults: Mapping[str, Any], generated_by: str,
               index: SnapshotIndex) -> Record:
    """Build one case record.

    Excerpts come from the snapshot in one of two ways. A ``digest`` entry
    names a block of a court's case page, and its sections are copied out
    whole. A ``quotes`` entry lists passages chosen from a judgment, and each
    must occur verbatim within the case's scope.

    Args:
        case_spec: One entry of the spec's ``cases`` list.
        defaults: Digest settings shared by every case of the spec.
        generated_by: Project-relative path of the spec.
        index: Snapshot index.

    Returns:
        The case record.

    Raises:
        KeyError: When a snapshot named by the spec is not registered.
        ValueError: When a block, heading or passage is not found.
    """
    record: Record = dict(case_spec["record"])
    scopes: Dict[str, Optional[Dict[str, str]]] = dict(case_spec.get("scopes", {}))
    excerpts: List[Record] = []
    if "digest" in case_spec:
        digest = {**defaults, **case_spec["digest"]}
        parts = _digest_parts(digest, index)
        record["source_title"] = parts["source_title"]
        excerpts.extend(parts["excerpts"])
        scopes[digest["source_id"]] = {"block_start": digest["block_start"], "block_end": digest["block_end"]}
    for quote in case_spec.get("quotes", []):
        if quote["source_id"] not in scopes:
            raise ValueError(f"{record['id']}: quote source {quote['source_id']} is not listed in scopes")
        if not index.found(quote["source_id"], quote["text"], scopes[quote["source_id"]]):
            raise ValueError(f"{record['id']}: passage not found in {quote['source_id']}: {quote['text'][:60]!r}")
        excerpts.append(dict(quote))
    if not excerpts:
        raise ValueError(f"{record['id']}: a case needs a digest block or at least one passage")
    for source_id in scopes:
        index.entry(source_id)
    for field in CASE_LIST_FIELDS:
        record.setdefault(field, [])
    record.setdefault("field_evidence", {})
    record["scopes"] = scopes
    record["scope_links"] = dict(case_spec.get("scope_links", {}))
    record["excerpts"] = excerpts
    record["generated_by"] = generated_by
    return record


def build_cases(spec: Mapping[str, Any], generated_by: str, index: SnapshotIndex) -> List[Record]:
    """Build every case of one spec."""
    defaults = spec.get("digest_defaults", {})
    return [build_case(case_spec, defaults, generated_by, index) for case_spec in spec["cases"]]


def regenerate(index: SnapshotIndex) -> Dict[str, Dict[str, Record]]:
    """Build every record again from the specs on disk.

    Returns:
        Records keyed by id, under ``instruments`` and ``cases``.

    Raises:
        KeyError: When a spec names an unknown snapshot or splitter.
        ValueError: When a spec no longer fits its snapshot.
    """
    instruments: Dict[str, Record] = {}
    for path in sorted((PATHS.specs / "instruments").glob("*.json")):
        record = build_instrument(load_spec(path), spec_ref(path), index)
        instruments[record["id"]] = record
    cases: Dict[str, Record] = {}
    for path in sorted((PATHS.specs / "cases").glob("*.json")):
        for record in build_cases(load_spec(path), spec_ref(path), index):
            cases[record["id"]] = record
    return {"instruments": instruments, "cases": cases}
