"""Snapshot one source into data/raw and register it in data/sources.json.

Usage:
    python tools/fetch.py SRC-ID URL --publisher NAME --kind OFFICIAL_TEXT --official
    python tools/fetch.py SRC-ID URL --publisher NAME --kind SECONDARY --proxy

``--proxy`` takes its address from the AIGOV_PROXY environment variable, so
no proxy address is written into the repository.
"""
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aigov.config import SOURCE_KINDS  # noqa: E402
from aigov.sources import read_text, snapshot  # noqa: E402

logger = logging.getLogger("fetch")


def main() -> int:
    """Parse arguments, take the snapshot and report what was stored."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_id")
    parser.add_argument("url")
    parser.add_argument("--publisher", required=True)
    parser.add_argument("--kind", required=True, choices=sorted(SOURCE_KINDS))
    parser.add_argument("--official", action="store_true")
    parser.add_argument("--proxy", action="store_true", help="route through $AIGOV_PROXY")
    parser.add_argument("--suffix", default=".html")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    proxy = None
    if args.proxy:
        proxy = os.environ.get("AIGOV_PROXY")
        if not proxy:
            logger.error("--proxy was given but AIGOV_PROXY is not set")
            return 2

    entry = snapshot(
        args.source_id,
        args.url,
        publisher=args.publisher,
        kind=args.kind,
        official=args.official,
        proxy=proxy,
        suffix=args.suffix,
        note=args.note,
    )
    text = read_text(entry) if args.suffix in (".html", ".htm", ".txt") else ""
    logger.info("%s sha256=%s bytes=%s text_chars=%d", entry["id"], entry["sha256"][:12], entry["bytes"], len(text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
