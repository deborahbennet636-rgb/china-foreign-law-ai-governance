"""Measure the coverage of the AGORA dataset and save the figures.

Usage:
    python -I tools/agora_stats.py

AGORA is used here as a benchmark and as a source of leads, never as a
source of text. This tool reads the downloaded archive and writes
``data/reference/agora-coverage.json`` so that every figure quoted in the
documentation can be recomputed.

The archive is third-party data under CC BY-NC 4.0. It stays in
``data/raw/agora`` and is not redistributed with the database.
"""
import csv
import hashlib
import io
import json
import logging
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "data" / "raw" / "agora" / "agora.zip"
RECORD = ROOT / "data" / "raw" / "agora" / "latest.json"
TARGET = ROOT / "data" / "reference" / "agora-coverage.json"
CHINA = "China"

logger = logging.getLogger("agora_stats")


def _table(archive: zipfile.ZipFile, name: str) -> List[Dict[str, str]]:
    """Read one CSV table of the archive."""
    with archive.open(name) as handle:
        return list(csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig")))


def measure() -> Dict[str, Any]:
    """Compute coverage figures from the archive.

    Returns:
        Counts by jurisdiction and status, and the list of Chinese documents
        with the host each one links to.

    Raises:
        FileNotFoundError: When the archive has not been downloaded.
    """
    csv.field_size_limit(10**9)
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    with zipfile.ZipFile(ARCHIVE) as archive:
        authorities = _table(archive, "agora/authorities.csv")
        documents = _table(archive, "agora/documents.csv")
    jurisdiction_of = {row["Name"]: row["Jurisdiction"] or "(none)" for row in authorities}

    by_jurisdiction = Counter(jurisdiction_of.get(row["Authority"], "(unknown)") for row in documents)
    by_status = Counter(row["Most recent activity"] for row in documents)
    china = [row for row in documents if jurisdiction_of.get(row["Authority"]) == CHINA]
    china_hosts = Counter(urlparse(row["Link to document"]).netloc for row in china)
    return {
        "dataset": "AGORA (AI GOvernance and Regulatory Archive)",
        "version": record["metadata"].get("version"),
        "doi": record.get("doi"),
        "published": record["metadata"].get("publication_date"),
        "license": record["metadata"].get("license", {}).get("id"),
        "archive_md5": hashlib.md5(ARCHIVE.read_bytes()).hexdigest(),
        "documents": len(documents),
        "by_jurisdiction": dict(by_jurisdiction.most_common()),
        "by_status": dict(by_status.most_common()),
        "china_documents": len(china),
        "china_link_hosts": dict(china_hosts.most_common()),
        "china_links_on_gov_cn": sum(count for host, count in china_hosts.items() if host.endswith(".gov.cn")),
        "china_list": [
            {
                "agora_id": row["AGORA ID"],
                "date": row["Most recent activity date"],
                "status": row["Most recent activity"],
                "name": row["Official name"],
            }
            for row in sorted(china, key=lambda row: row["Most recent activity date"])
        ],
    }


def main() -> int:
    """Write the coverage file and print the headline figures."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        figures = measure()
    except FileNotFoundError as error:
        logger.error("archive not downloaded: %s", error)
        return 1
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(figures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("v%s: %d documents, %s", figures["version"], figures["documents"], figures["by_jurisdiction"])
    logger.info("China: %d documents, linked hosts %s", figures["china_documents"], figures["china_link_hosts"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
