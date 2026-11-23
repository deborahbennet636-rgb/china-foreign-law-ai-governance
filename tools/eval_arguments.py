"""Evaluate inter-annotator agreement (Cohen's kappa) or LLM-vs-Human accuracy.

Supports CSV (UTF-8 / UTF-8-SIG) and JSONL annotation files.

Examples:
    # Double-blind human agreement (Annotator A vs Annotator B):
    python -I tools/eval_arguments.py \
        --a research/lamus_pilot/blind_review_annotator_A.csv --col-a human_role \
        --b research/lamus_pilot/blind_review_annotator_B.csv --col-b human_role \
        --by-jurisdiction

    # Hybrid audit (LLM draft vs human verified in the same file):
    python -I tools/eval_arguments.py \
        --a research/lamus_pilot/hybrid_audit_sheet.csv --col-a verified_role \
        --b research/lamus_pilot/hybrid_audit_sheet.csv --col-b draft_role \
        --by-jurisdiction
"""
import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aigov.argument_metrics import DEFAULT_LABELS, evaluate_aligned_records  # noqa: E402


def load_rows(path: Path) -> List[Dict[str, Any]]:
    """Load annotation rows from CSV or JSONL."""
    if path.suffix.lower() == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def format_report(result: Dict[str, Any]) -> str:
    """Format evaluation metrics as readable plain text / Markdown."""
    ov = result["overall"]
    lines = [
        (
            f"Evaluated pairs: {ov['n']} (common={result['common_rows']}, "
            f"unlabeled_skipped={result['unlabeled_skipped']}, "
            f"only_in_a={result['only_in_a']}, only_in_b={result['only_in_b']})"
        ),
        f"Agreement (Accuracy): {ov['accuracy']:.4f} ({ov['agreements']}/{ov['n']})",
        f"Disagreement / Correction Rate: {ov['disagreement_rate']:.4f} ({ov['disagreements']}/{ov['n']})",
        f"Cohen's kappa (unweighted): {ov['cohens_kappa']:.4f}",
        f"Macro-F1 (present classes): {ov['macro_f1_present']:.4f} | Macro-F1 (all 6): {ov['macro_f1_all']:.4f} | Weighted-F1: {ov['weighted_f1']:.4f}",
        "",
        "Per-class metrics:",
        f"{'Role':12s} {'Prec':>7s} {'Rec':>7s} {'F1':>7s} {'Supp':>6s} {'Pred':>6s}",
    ]
    for label in DEFAULT_LABELS:
        m = ov["per_class"][label]
        lines.append(
            f"{label:12s} {m['precision']:7.4f} {m['recall']:7.4f} {m['f1']:7.4f} {m['support']:6d} {m['predicted']:6d}"
        )

    lines.append("")
    lines.append("Confusion Matrix (rows=A, cols=B):")
    header = f"{'A \\ B':12s}" + "".join(f"{lab[:6]:>8s}" for lab in DEFAULT_LABELS)
    lines.append(header)
    for row_lab in DEFAULT_LABELS:
        row_vals = "".join(f"{ov['confusion_matrix'][row_lab][col_lab]:8d}" for col_lab in DEFAULT_LABELS)
        lines.append(f"{row_lab:12s}{row_vals}")

    if "by_jurisdiction" in result:
        lines.append("")
        lines.append("By jurisdiction:")
        for jur, jm in result["by_jurisdiction"].items():
            lines.append(
                f"  {jur}: n={jm['n']}, acc={jm['accuracy']:.4f}, kappa={jm['cohens_kappa']:.4f}, macro_f1={jm['macro_f1_present']:.4f}"
            )

    if result["disagreements"]:
        lines.append("")
        lines.append(f"Disagreements ({len(result['disagreements'])}):")
        for item in result["disagreements"][:30]:
            snippet = item["text"][:60].replace("\n", " ")
            lines.append(
                f"  {item['case_id']} {item['sentence_id']} [{item['jurisdiction']}]: "
                f"A={item['label_a']} vs B={item['label_b']} | {snippet}"
            )
        if len(result["disagreements"]) > 30:
            lines.append(f"  ... and {len(result['disagreements']) - 30} more")

    return "\n".join(lines)


def main() -> None:
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Evaluate FIRAC sentence-level annotations.")
    parser.add_argument("--a", required=True, help="First CSV/JSONL file (reference / Annotator A)")
    parser.add_argument("--b", required=True, help="Second CSV/JSONL file (prediction / Annotator B)")
    parser.add_argument("--col-a", default="human_role", help="Label column name in file A")
    parser.add_argument("--col-b", default="human_role", help="Label column name in file B")
    parser.add_argument("--by-jurisdiction", action="store_true", help="Include CN/EU/US breakdown")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of text report")
    args = parser.parse_args()

    result = evaluate_aligned_records(
        load_rows(Path(args.a)),
        load_rows(Path(args.b)),
        col_a=args.col_a,
        col_b=args.col_b,
        by_jurisdiction=args.by_jurisdiction,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result))


if __name__ == "__main__":
    main()
