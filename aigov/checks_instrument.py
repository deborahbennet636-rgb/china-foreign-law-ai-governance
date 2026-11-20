"""Checks on instrument records.

What is checked mechanically: the title, the document number, the issuer's
names, each date against a quote of its own, every provision with its label,
and any claim that one instrument amends another. What is not: ``level``,
``instrument_type`` and ``short_title`` are the editor's classification, and
the viewer says so.
"""
import datetime
from typing import Any, Dict, List, Mapping, Optional, Set

from .config import INSTRUMENT_STATUS, INSTRUMENT_TYPES
from .evidence import SnapshotIndex, contains_name, long_enough, quote_states_date, states_token
from .textnorm import normalize

Record = Dict[str, Any]

DATE_FIELDS = ("published_at", "effective_at")
ISSUER_SEPARATOR = "、"
MIN_DOC_NUMBER_CHARS = 8
MIN_ISSUER_CHARS = 3
# Entry-into-force clauses count days in words. Only counts listed here can
# be derived; anything else has to be stated by the source or left empty.
ORDINAL_DAYS = {3: "third", 7: "seventh", 10: "tenth", 15: "fifteenth", 20: "twentieth", 30: "thirtieth"}
# Some instruments take effect the day they are promulgated, so their text
# holds no date to quote. The clause that says so is quoted instead, and the
# date is taken from the publication date — still a derivation, still checked.
ON_PUBLICATION_CLAUSES = ("自公布之日起施行", "自发布之日起施行", "自印发之日起施行", "自公布之日起生效")
STATUS_NEEDING_EVIDENCE = frozenset({"PROPOSED", "REPEALED", "UNKNOWN"})


def _parse_date(value: Any) -> Optional[datetime.date]:
    """Parse an ISO date, returning None when it is not one."""
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        return None


def _check_provisions(owner: str, record: Record, index: SnapshotIndex) -> List[str]:
    """Check each provision, label and text together, against its snapshot."""
    errors = []
    sources = record.get("source_ids", [])
    provisions = record.get("provisions", [])
    for provision in provisions:
        whole = " ".join(part for part in (provision["no"], provision.get("heading", ""), provision.get("text", "")) if part)
        source_id = provision.get("source_id")
        if source_id not in sources:
            errors.append(f"{owner} {provision['no']}: provision source {source_id!r} is not one of the record's sources")
        elif not provision.get("text") or not index.found(source_id, whole):
            errors.append(f"{owner} {provision['no']}: label and text do not occur together in the snapshot")
    if record.get("complete"):
        ordinals = [provision["ordinal"] for provision in provisions]
        if ordinals != list(range(1, int(record.get("expected_provisions") or 0) + 1)):
            errors.append(f"{owner}: marked complete but provisions are not 1..{record.get('expected_provisions')}")
    return errors


def _check_derived(owner: str, field: str, record: Record, rule: Mapping[str, Any], evidence: Mapping[str, str]) -> List[str]:
    """Check a date that the source gives only as a rule.

    The one rule supported is "N days after publication", where the quoted
    clause must name N in words. The date is recomputed here.
    """
    stated = _parse_date(record.get(field))
    base = _parse_date(record.get("published_at"))
    days = rule.get("plus_days")
    if field != "effective_at" or rule.get("from") != "published_at" or base is None:
        return [f"{owner}: only effective_at may be derived, and only from a stated published_at"]
    if "published_at" in record.get("derived_dates", {}) or (days != 0 and days not in ORDINAL_DAYS):
        return [f"{owner}: derivation of {field} needs a day count of 0 or one of {sorted(ORDINAL_DAYS)}, got {days!r}"]
    if days == 0:
        clause = normalize(evidence.get(rule.get("basis", ""), ""))
        if not any(stated_clause in clause for stated_clause in ON_PUBLICATION_CLAUSES):
            return [f"{owner}: the quoted rule for {field} does not say it takes effect on publication"]
        if stated != base:
            return [f"{owner}: {field}={record.get(field)} is not the publication date"]
        return []
    clause = normalize(evidence.get(rule.get("basis", ""), "")).casefold()
    if f"{ORDINAL_DAYS[days]}day" not in clause:
        return [f"{owner}: the quoted rule for {field} does not say '{ORDINAL_DAYS[days]} day'"]
    if stated != base + datetime.timedelta(days=days):
        return [f"{owner}: {field}={record.get(field)} is not published_at plus {days} days"]
    return []


def _check_date(owner: str, field: str, record: Record, evidence: Mapping[str, str]) -> List[str]:
    """Check one date field against its own quote, or against its derivation."""
    value = record.get(field)
    rule = record.get("derived_dates", {}).get(field)
    if not value:
        return [f"{owner}: {field} is empty but has a derivation rule"] if rule else []
    if _parse_date(value) is None:
        return [f"{owner}: {field}={value!r} is not a date"]
    if rule is not None:
        return _check_derived(owner, field, record, rule, evidence)
    if not quote_states_date(evidence.get(field, ""), value):
        return [f"{owner}: {field}={value} is not stated in meta_evidence[{field!r}]"]
    return []


def _check_identity(owner: str, record: Record, index: SnapshotIndex, evidence: Mapping[str, str]) -> List[str]:
    """Check title, document number and issuer.

    Title and document number must stand in the first source. A quote given
    as evidence may come from any source of the record, since a statute
    published over several pages states its commencement on the last one.
    """
    errors = []
    source_id = record["source_id"]
    title = record.get("title", "")
    if not long_enough(title) or not index.found(source_id, title, ignore_case=True):
        errors.append(f"{owner}: title does not occur in the snapshot")
    for field, quote in evidence.items():
        if not long_enough(quote) or not any(index.found(item, quote) for item in record["source_ids"]):
            errors.append(f"{owner}: meta_evidence[{field!r}] is too short or not in the snapshot")
    number = record.get("doc_number")
    if number is not None:
        whole = len(normalize(number)) >= MIN_DOC_NUMBER_CHARS and index.found(source_id, number, ignore_case=True)
        if not whole:
            errors.append(f"{owner}: doc_number {number!r} must occur verbatim, in full, in the snapshot")
    issuer = record.get("issuer")
    if issuer is not None:
        quoted = evidence.get("issuer", "")
        missing = [part for part in issuer.split(ISSUER_SEPARATOR) if not contains_name(quoted, part, MIN_ISSUER_CHARS)]
        if missing:
            errors.append(f"{owner}: issuer names not found in meta_evidence['issuer']: {missing}")
    return errors


def _check_status(owner: str, record: Record, amended: Set[str], evidence: Mapping[str, str], today: datetime.date) -> List[str]:
    """Check that the status is one the record's own facts allow."""
    status = record.get("status")
    effective = _parse_date(record.get("effective_at"))
    if status == "IN_FORCE" and (effective is None or effective > today):
        return [f"{owner}: IN_FORCE needs an effective date that has passed"]
    if status == "ADOPTED" and _parse_date(record.get("published_at")) is None:
        return [f"{owner}: ADOPTED needs a publication date"]
    if status == "AMENDED" and record.get("id") not in amended:
        return [f"{owner}: AMENDED, but no instrument in the database amends it"]
    if status in STATUS_NEEDING_EVIDENCE and "status" not in evidence:
        return [f"{owner}: status {status} needs meta_evidence['status']"]
    return []


def check_instrument(record: Record, index: SnapshotIndex, by_id: Mapping[str, Record], today: datetime.date) -> List[str]:
    """Check one instrument record.

    Args:
        record: The instrument record.
        index: Snapshot index.
        by_id: Every instrument in the database, keyed by id.
        today: The date against which "in force" is judged.

    Returns:
        One message per problem found.
    """
    owner = record.get("id", "?")
    errors = []
    if record.get("instrument_type") not in INSTRUMENT_TYPES:
        errors.append(f"{owner}: unknown instrument_type {record.get('instrument_type')!r}")
    if record.get("status") not in INSTRUMENT_STATUS:
        errors.append(f"{owner}: unknown status {record.get('status')!r}")
    source_id = record.get("source_id", "")
    sources = record.get("source_ids", [])
    unregistered = [item for item in [source_id, *sources] if not index.has(item)]
    if unregistered or source_id not in sources:
        return errors + [f"{owner}: sources are not registered or the main source is not listed: {unregistered}"]

    evidence: Dict[str, str] = record.get("meta_evidence", {})
    errors += _check_identity(owner, record, index, evidence)
    errors += _check_provisions(owner, record, index)
    for field in DATE_FIELDS:
        errors += _check_date(owner, field, record, evidence)

    if "amended_by" in record:
        errors.append(f"{owner}: amended_by is computed from other records' amends and must not be typed")
    for target in record.get("amends", []):
        number = (by_id.get(target) or {}).get("doc_number")
        if not number or not states_token(evidence.get("amends", "").casefold(), number.casefold()):
            errors.append(f"{owner}: meta_evidence['amends'] does not name the document number of {target!r}")
    amended = {target for other in by_id.values() for target in other.get("amends", [])}
    return errors + _check_status(owner, record, amended, evidence, today)
