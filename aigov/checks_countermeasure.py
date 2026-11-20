"""Checks on countermeasure records.

Layer 4 of the database is the one that makes "涉外" mean something: measures
a foreign state or the EU takes against Chinese parties, and measures China
takes in response. The two directions never share a record, because reading
them as one list is how a comparison turns into a claim.

A countermeasure is checked the way an instrument is: the measure's title must
occur in a registered snapshot, its date must be stated by a quote of its own,
and any instrument it rests on must exist in the database.
"""
import datetime
from typing import Any, Dict, List, Mapping, Optional

from .config import MEASURE_DIRECTIONS, MEASURE_STATUS, MEASURE_TYPES
from .evidence import quote_states_date, states_token
from .textnorm import normalize

Record = Dict[str, Any]

DATE_FIELDS = ("announced_at", "effective_at")
MIN_TITLE_CHARS = 6
# A notice that takes effect the day it is published states no date of its
# own. The clause is quoted and the date is taken from the announcement.
ON_PUBLICATION_CLAUSES = ("自公布之日起实施", "自公布之日起施行", "effective upon publication")


def _parse_date(value: Any) -> Optional[datetime.date]:
    """Parse an ISO date, returning None when it is not one."""
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        return None


def check_countermeasure(record: Record, instrument_by_id: Mapping[str, Record],
                         index: Any) -> List[str]:
    """Check one countermeasure record.

    Args:
        record: The countermeasure record.
        instrument_by_id: Every instrument in the database, keyed by id.
        index: Snapshot index, used to confirm the title and dates.

    Returns:
        One message per problem found.
    """
    owner = record.get("id", "?")
    errors = []

    if record.get("direction") not in MEASURE_DIRECTIONS:
        errors.append(f"{owner}: unknown direction {record.get('direction')!r}")
    if record.get("measure_type") not in MEASURE_TYPES:
        errors.append(f"{owner}: unknown measure_type {record.get('measure_type')!r}")
    if record.get("status") not in MEASURE_STATUS:
        errors.append(f"{owner}: unknown status {record.get('status')!r}")

    source_id = record.get("source_id", "")
    sources = record.get("source_ids", [])
    unregistered = [item for item in [source_id, *sources] if not index.has(item)]
    if unregistered or source_id not in sources:
        return errors + [f"{owner}: sources are not registered or the main source is not listed: {unregistered}"]

    title = record.get("title", "")
    if len(normalize(title)) < MIN_TITLE_CHARS or not index.found(source_id, title, ignore_case=True):
        errors.append(f"{owner}: title does not occur in the snapshot")

    evidence: Dict[str, str] = record.get("meta_evidence", {})
    for field in DATE_FIELDS:
        value = record.get(field)
        if not value:
            continue
        if _parse_date(value) is None:
            errors.append(f"{owner}: {field}={value!r} is not a date")
        elif field == "effective_at" and record.get("effective_on_publication"):
            # Checked below instead: the text gives no date, only the rule.
            continue
        elif not quote_states_date(evidence.get(field, ""), value):
            errors.append(f"{owner}: {field}={value} is not stated in meta_evidence[{field!r}]")

    if record.get("effective_on_publication"):
        clause = normalize(evidence.get("effective_at", ""))
        if not any(stated_clause in clause for stated_clause in ON_PUBLICATION_CLAUSES):
            errors.append(f"{owner}: effective_on_publication is set but meta_evidence['effective_at'] does not say so")
        if record.get("effective_at") != record.get("announced_at"):
            errors.append(f"{owner}: effective_on_publication means effective_at must equal announced_at")

    for field, quote in evidence.items():
        if not quote or not any(index.found(item, quote) for item in record["source_ids"]):
            errors.append(f"{owner}: meta_evidence[{field!r}] is empty or not in the snapshot")

    instrument_id = record.get("instrument_id")
    if instrument_id is not None and instrument_id not in instrument_by_id:
        errors.append(f"{owner}: unknown instrument {instrument_id!r}")

    target = record.get("target")
    if not target or not normalize(str(target)):
        errors.append(f"{owner}: a countermeasure needs a target")

    if record.get("status") == "IN_FORCE":
        effective = _parse_date(record.get("effective_at"))
        if effective is None:
            errors.append(f"{owner}: IN_FORCE needs an effective date")
    return errors


def states_parties(quote: str, name: str) -> bool:
    """Tell whether a quote names a party to the measure."""
    return bool(name) and states_token(normalize(quote), normalize(name))
