"""Validate the database and build the published files.

Usage:
    python tools/build.py            validate, then write dist/
    python tools/build.py --check    validate only

The build stops when validation fails: a record whose quotes do not match
their snapshots is never published. Outputs:

    dist/index.html      single-file viewer, works offline
    dist/aigov-db.json   the same dataset for analysis
"""
import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aigov.build import build_dataset, render_page  # noqa: E402
from aigov.config import PATHS  # noqa: E402
from aigov.store import load_database  # noqa: E402
from aigov.validate import validate  # noqa: E402

logger = logging.getLogger("build")


def main() -> int:
    """Validate, then build unless ``--check`` was given."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="validate only, write nothing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    database = load_database()
    errors = validate(database)
    for message in errors:
        logger.error(message)
    if errors:
        logger.error("%d problems; nothing was built", len(errors))
        return 1
    logger.info("validation passed")
    if args.check:
        return 0

    dataset = build_dataset(database)
    PATHS.dist.mkdir(parents=True, exist_ok=True)
    (PATHS.dist / "aigov-db.json").write_text(
        json.dumps(dataset, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    page = render_page(dataset)
    # Line endings are fixed so the bytes match the hashes in the page's policy.
    (PATHS.dist / "index.html").write_text(page, encoding="utf-8", newline="\n")
    logger.info("stats: %s", json.dumps(dataset["stats"], ensure_ascii=False))
    logger.info("wrote dist/index.html (%d KB) and dist/aigov-db.json", len(page.encode("utf-8")) // 1024)
    return 0


if __name__ == "__main__":
    sys.exit(main())
