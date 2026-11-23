"""Export LAMUS pilot review sheets (blind double-review + hybrid audit) and JSONL corpus.

Usage:
    python -I tools/export_review_sheet.py [--out research/lamus_pilot]
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aigov.build import build_dataset  # noqa: E402
from aigov.store import load_database  # noqa: E402
from aigov.validate import validate  # noqa: E402


_EXCEL_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: str) -> str:
    """Neutralize spreadsheet formula injection on free-text CSV columns."""
    if value and value[0] in _EXCEL_FORMULA_PREFIXES:
        return "'" + value
    return value


def export_pilot(out_dir: Path) -> None:
    """Validate database and write blind review CSVs, hybrid audit CSV, and JSONL corpus."""
    db = load_database()
    problems = validate(db)
    if problems:
        raise SystemExit("validation failed:\n" + "\n".join(problems[:20]))

    dataset = build_dataset(db)
    cases_by_id = {c["id"]: c for c in dataset["cases"]}
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for arg in sorted(dataset["arguments"], key=lambda item: item["case_id"]):
        case = cases_by_id[arg["case_id"]]
        excerpts = case.get("excerpts", [])
        for sent in arg["sentences"]:
            ex_idx = sent["excerpt_index"]
            rows.append({
                "case_id": arg["case_id"],
                "jurisdiction": case["jurisdiction"],
                "verification": arg["verification"],
                "evidence_grade": arg["evidence_grade"],
                "excerpt_index": ex_idx,
                "excerpt_kind": excerpts[ex_idx]["kind"],
                "source_id": sent["source_id"],
                "sentence_id": sent["id"],
                "text": sent["text"],
                "draft_role": sent["role"],
                "draft_rationale": sent.get("rationale", ""),
                "provisions_mentioned": sent.get("provisions_mentioned", []),
                "annotation_mode": arg["annotation_mode"],
                "annotator": arg["annotator"],
            })

    # 1. Double-blind review templates (UTF-8 with BOM for Excel compatibility; no LLM label leaked).
    blind_fields = [
        "case_id",
        "jurisdiction",
        "excerpt_kind",
        "sentence_id",
        "text",
        "human_role",
        "notes",
    ]
    for suffix in ("annotator_A", "annotator_B"):
        path = out_dir / f"blind_review_{suffix}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=blind_fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    "case_id": row["case_id"],
                    "jurisdiction": row["jurisdiction"],
                    "excerpt_kind": row["excerpt_kind"],
                    "sentence_id": row["sentence_id"],
                    "text": _csv_safe(row["text"]),
                    "human_role": "",
                    "notes": "",
                })

    # 2. Hybrid LLM-screening + human-correction sheet (mirrors LAMUS Section 3.2 workflow).
    hybrid_fields = [
        "case_id",
        "jurisdiction",
        "excerpt_kind",
        "sentence_id",
        "text",
        "draft_role",
        "draft_rationale",
        "verified_role",
        "notes",
    ]
    with (out_dir / "hybrid_audit_sheet.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=hybrid_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "case_id": row["case_id"],
                "jurisdiction": row["jurisdiction"],
                "excerpt_kind": row["excerpt_kind"],
                "sentence_id": row["sentence_id"],
                "text": _csv_safe(row["text"]),
                "draft_role": row["draft_role"],
                "draft_rationale": _csv_safe(row["draft_rationale"]),
                "verified_role": "",
                "notes": "",
            })

    # 3. Machine-readable JSONL corpus (for downstream model fine-tuning / evaluation).
    with (out_dir / "pilot_corpus.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"exported {len(rows)} sentences across {len(dataset['arguments'])} cases to {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export LAMUS FIRAC review sheets and JSONL corpus.")
    parser.add_argument("--out", default=str(ROOT / "research" / "lamus_pilot"))
    args = parser.parse_args()
    export_pilot(Path(args.out))


if __name__ == "__main__":
    main()
