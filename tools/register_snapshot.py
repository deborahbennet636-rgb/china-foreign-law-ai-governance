"""Register a page captured from a logged-in browser as a source snapshot.

Usage:
    python tools/register_snapshot.py SRC-ID captured.html --url URL --publisher NAME --kind JUDGMENT

Used for subscription databases, which ``tools/fetch.py`` cannot reach.
Capture the page with ``tools/browser.cjs save`` first.
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aigov.config import SOURCE_KINDS  # noqa: E402
from aigov.sources import register_file  # noqa: E402

logger = logging.getLogger("register_snapshot")


def main() -> int:
    """Parse arguments and register the captured file."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source_id")
    parser.add_argument("file", type=Path)
    parser.add_argument("--url", required=True)
    parser.add_argument("--publisher", required=True)
    parser.add_argument("--kind", required=True, choices=sorted(SOURCE_KINDS))
    parser.add_argument("--official", action="store_true")
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        entry = register_file(args.source_id, args.file, args.url, args.publisher, args.kind, args.official, args.note)
    except (ValueError, OSError) as error:
        logger.error("%s", error)
        return 1
    logger.info("%s sha256=%s", entry["id"], entry["sha256"][:12])
    return 0


if __name__ == "__main__":
    sys.exit(main())
