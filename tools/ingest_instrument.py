"""Build instrument records from ingest specs.

Usage:
    python tools/ingest_instrument.py ingest/instruments/CN-CAC-GENAI-2023.json
    python tools/ingest_instrument.py ingest/instruments/*.json

The spec names the snapshot, the drafting style and the number of provisions
the instrument is known to have. A record whose numbering has a gap is not
written, so a page that was cut off fails loudly instead of producing a
short record. See ``aigov/ingest.py`` for the modes.
"""
import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aigov.config import PATHS  # noqa: E402
from aigov.evidence import SnapshotIndex  # noqa: E402
from aigov.ingest import build_instrument, load_spec, spec_ref  # noqa: E402
from aigov.sources import load_manifest  # noqa: E402

logger = logging.getLogger("ingest_instrument")


def main() -> int:
    """Ingest every spec given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("specs", nargs="+", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    index = SnapshotIndex(load_manifest())
    PATHS.instruments.mkdir(parents=True, exist_ok=True)
    for spec_path in args.specs:
        try:
            record = build_instrument(load_spec(spec_path), spec_ref(spec_path), index)
        except (KeyError, ValueError, OSError) as error:
            logger.error("%s: %s", spec_path.name, error)
            return 1
        target = PATHS.instruments / f"{record['id']}.json"
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        logger.info("%s: %d provisions -> %s", record["id"], len(record["provisions"]), target.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
