"""Load the records of the database from disk."""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set

from .config import PATHS
from .sources import load_manifest

Record = Dict[str, Any]


@dataclass(frozen=True)
class Database:
    """Everything the validator and the builder read."""

    manifest: Dict[str, Record]
    instruments: List[Record]
    cases: List[Record]
    issues: List[Record]
    leads: List[Record]
    # v1 layers. Defaulted so that every caller written before v1 still builds
    # a database, and so that a database without them is a valid one.
    obligations: List[Record] = field(default_factory=list)
    countermeasures: List[Record] = field(default_factory=list)


def _load_dir(path: Path) -> List[Record]:
    """Read every JSON record of a directory, in file-name order."""
    return [json.loads(item.read_text(encoding="utf-8")) for item in sorted(path.glob("*.json"))]


def _load_list(path: Path) -> List[Record]:
    """Read a JSON file holding a list of records; a missing file is empty."""
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def load_database() -> Database:
    """Read the whole database."""
    return Database(
        manifest=load_manifest(),
        instruments=_load_dir(PATHS.instruments),
        cases=_load_dir(PATHS.cases),
        issues=_load_list(PATHS.issues / "issues.json"),
        leads=_load_list(PATHS.leads / "leads.json"),
        obligations=_load_dir(PATHS.obligations) if PATHS.obligations.exists() else [],
        countermeasures=_load_dir(PATHS.countermeasures) if PATHS.countermeasures.exists() else [],
    )


def provision_ref(instrument_id: str, label: str) -> str:
    """Build the reference used to point at one provision."""
    return f"{instrument_id}#{label}"


def provision_refs(instruments: List[Record]) -> Set[str]:
    """Return the reference of every provision in the database."""
    return {
        provision_ref(instrument["id"], provision["no"])
        for instrument in instruments
        for provision in instrument["provisions"]
    }
