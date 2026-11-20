"""Checks that every record must pass before the database is built.

The rule behind all of them: a field that states a fact about a law or a
case must point at a snapshot where that fact can be read. A record that
cannot show its evidence does not build.
"""
import datetime
from typing import Any, Dict, List, Optional, Set

from .checks_case import check_case
from .checks_countermeasure import check_countermeasure
from .checks_instrument import check_instrument
from .checks_obligation import check_obligation
from .config import LEAD_STATUS, MATERIAL_NATURES, PATHS
from .evidence import SnapshotIndex
from .ingest import regenerate
from .sources import sha256_of
from .store import Database, Record, provision_ref, provision_refs


def check_manifest(manifest: Dict[str, Record]) -> List[str]:
    """Check that every snapshot, and every stored text layer, is unchanged."""
    errors = []
    for source_id, entry in manifest.items():
        files = [(entry["file"], entry["sha256"])]
        if entry["file"].endswith(".pdf"):
            if "text_file" not in entry:
                errors.append(f"{source_id}: a PDF snapshot needs a stored text layer")
                continue
            files.append((entry["text_file"], entry["text_sha256"]))
        for name, expected in files:
            path = PATHS.data / name
            if not path.exists():
                errors.append(f"{source_id}: file missing: {name}")
            elif sha256_of(path.read_bytes()) != expected:
                errors.append(f"{source_id}: {name} changed on disk since it was registered")
    return errors


def check_regenerated(database: Database, index: SnapshotIndex) -> List[str]:
    """Check that stored records equal what their specs produce today.

    This is what ties a provision's label to its text and an excerpt to its
    case: neither is typed, both are cut from the snapshot again and compared.
    """
    try:
        fresh = regenerate(index)
    except (KeyError, ValueError, OSError) as error:
        return [f"records could not be regenerated from their specs: {error}"]
    errors = []
    for kind, stored in (("instruments", database.instruments), ("cases", database.cases)):
        stored_by_id = {record["id"]: record for record in stored}
        for record_id in sorted(set(stored_by_id) | set(fresh[kind])):
            if record_id not in fresh[kind]:
                errors.append(f"{record_id}: stored record has no ingest spec")
            elif record_id not in stored_by_id:
                errors.append(f"{record_id}: spec exists but the record was not ingested")
            elif stored_by_id[record_id] != fresh[kind][record_id]:
                errors.append(f"{record_id}: stored record differs from what its spec produces; run the ingest tool")
    return errors


def check_issue(record: Record, refs: Set[str], case_ids: Set[str],
                obligation_ids: Set[str] = frozenset()) -> List[str]:
    """Check one issue record.

    An issue is where this database differs most from a plain corpus: it puts
    jurisdictions side by side. Two fields keep that honest. ``nature`` says
    what kind of material a position rests on, so a statute is never read as
    if it were a holding. ``comparison`` says whether the positions can be
    compared at all, and why not when they cannot.
    """
    owner = record.get("id", "?")
    errors = []
    for position in record.get("positions", []):
        where = f"{owner}/{position.get('jurisdiction')}"
        if not position.get("summary"):
            errors.append(f"{where}: a position needs a summary, even if it says the database holds nothing")
        nature = position.get("nature")
        if nature is not None and nature not in MATERIAL_NATURES:
            errors.append(f"{where}: unknown material nature {nature!r}")
        errors += [f"{where}: unknown provision {ref!r}" for ref in position.get("provisions", []) if ref not in refs]
        errors += [f"{where}: unknown case {case!r}" for case in position.get("cases", []) if case not in case_ids]
        errors += [
            f"{where}: unknown obligation {item!r}"
            for item in position.get("obligations", [])
            if item not in obligation_ids
        ]

    comparison = record.get("comparison")
    if comparison is not None:
        if not isinstance(comparison.get("comparable"), bool):
            errors.append(f"{owner}: comparison needs comparable true or false")
        elif comparison["comparable"] is False and not comparison.get("reason"):
            errors.append(f"{owner}: comparison says the positions are not comparable but gives no reason")
        elif comparison["comparable"] is True and not all(
            position.get("summary") for position in record.get("positions", [])
        ):
            errors.append(f"{owner}: comparison says comparable, but a position is empty")
    return errors


def check_lead(record: Record) -> List[str]:
    """Check one lead: an unverified pointer must say where it was seen."""
    owner = record.get("id", "?")
    errors = []
    if record.get("status") not in LEAD_STATUS:
        errors.append(f"{owner}: unknown lead status {record.get('status')!r}")
    for field in ("title", "claim", "seen_in", "next_step"):
        if not record.get(field):
            errors.append(f"{owner}: lead is missing {field}")
    return errors


def _cross_checks(database: Database, refs: Set[str]) -> List[str]:
    """Checks that span record types."""
    errors = []
    groups = (
        database.instruments,
        database.cases,
        database.issues,
        database.leads,
        database.obligations,
        database.countermeasures,
    )
    ids = [record["id"] for group in groups for record in group]
    errors += [f"{item}: id is used more than once" for item in sorted({item for item in ids if ids.count(item) > 1})]

    listed: Dict[str, Set[str]] = {issue["id"]: set() for issue in database.issues}
    used: Set[Any] = set()
    for issue in database.issues:
        for position in issue.get("positions", []):
            listed[issue["id"]].update(position.get("cases", []))
            used.update(position.get("provisions", []))
    for case in database.cases:
        used.update(anchor.get("provision") for anchor in case.get("legal_anchors", []))
        for issue_id in case.get("issues", []):
            if issue_id in listed and case["id"] not in listed[issue_id]:
                errors.append(f"{case['id']}: tagged {issue_id} but not listed in any of its positions")
    for instrument in database.instruments:
        if instrument.get("instrument_type") != "GENERAL_LAW_CITED":
            continue
        for provision in instrument["provisions"]:
            ref = provision_ref(instrument["id"], provision["no"])
            if ref not in used:
                errors.append(f"{ref}: general-law provision is not used by any case or issue")
    return errors


def validate(database: Database, index: Optional[SnapshotIndex] = None, check_files: bool = True,
             today: Optional[datetime.date] = None) -> List[str]:
    """Run every check.

    Args:
        database: The loaded database.
        index: Snapshot index to check quotes against. Defaults to one that
            reads the snapshots named by the manifest from disk.
        check_files: Whether to verify snapshot hashes and to regenerate
            every record from its spec. Tests on in-memory data turn it off.
        today: Date against which "in force" is judged; defaults to today.

    Returns:
        One message per problem found; an empty list means the database
        may be built.
    """
    index = index or SnapshotIndex(database.manifest)
    today = today or datetime.date.today()
    refs = provision_refs(database.instruments)
    instruments = {record["id"]: record for record in database.instruments}
    case_ids = {record["id"] for record in database.cases}
    issue_ids = {record["id"] for record in database.issues}

    errors = check_manifest(database.manifest) if check_files else []
    if errors:
        return errors
    if check_files:
        errors += check_regenerated(database, index)
    for record in database.instruments:
        errors += check_instrument(record, index, instruments, today)
    for record in database.cases:
        errors += check_case(record, index, instruments, refs, issue_ids)
    obligation_ids = {record["id"] for record in database.obligations}
    for record in database.issues:
        errors += check_issue(record, refs, case_ids, obligation_ids)
    for record in database.leads:
        errors += check_lead(record)
    for record in database.obligations:
        errors += check_obligation(record, instruments, refs)
    for record in database.countermeasures:
        errors += check_countermeasure(record, instruments, index)
    return errors + _cross_checks(database, refs)
