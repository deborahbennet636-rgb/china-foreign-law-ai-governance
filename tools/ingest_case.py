"""Build case records from ingest specs.

Usage:
    python tools/ingest_case.py ingest/cases/cn-spc.json
    python tools/ingest_case.py ingest/cases/*.json

A spec lists cases. Each takes its excerpts from the snapshot either as a
``digest`` block of a court's case page, copied out whole, or as ``quotes``
chosen from a judgment and checked verbatim. Everything else about the case
is the editor's reading and lives under ``record``, each fact with a quote
of its own. See ``aigov/ingest.py`` and ``aigov/checks_case.py``.
"""
import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aigov.config import PATHS  # noqa: E402
from aigov.evidence import SnapshotIndex  # noqa: E402
from aigov.ingest import build_cases, load_spec, spec_ref  # noqa: E402
from aigov.sources import load_manifest  # noqa: E402

logger = logging.getLogger("ingest_case")


def main() -> int:
    """Ingest every spec given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("specs", nargs="+", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    index = SnapshotIndex(load_manifest())
    PATHS.cases.mkdir(parents=True, exist_ok=True)
    for spec_path in args.specs:
        try:
            records = build_cases(load_spec(spec_path), spec_ref(spec_path), index)
        except (KeyError, ValueError, OSError) as error:
            logger.error("%s: %s", spec_path.name, error)
            return 1
        for record in records:
            target = PATHS.cases / f"{record['id']}.json"
            target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            logger.info("%s: %d excerpts -> %s", record["id"], len(record["excerpts"]), target.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
