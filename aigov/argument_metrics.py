"""Inter-annotator agreement and classification metrics for FIRAC annotations.

Pure standard-library implementation of unweighted Cohen's kappa, per-class
precision/recall/F1, macro-F1, confusion matrix, and disagreement extraction
for the LAMUS-style sentence-level legal argument mining pilot.
"""
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set, Tuple

from .config import ARGUMENT_ROLES

DEFAULT_LABELS: Tuple[str, ...] = (
    "FACT",
    "ISSUE",
    "RULE",
    "ANALYSIS",
    "CONCLUSION",
    "OTHER",
)


def _validate_inputs(
    labels_a: Sequence[str],
    labels_b: Sequence[str],
    categories: Sequence[str],
) -> Set[str]:
    """Validate aligned label sequences and non-duplicate category vocabulary."""
    if not categories:
        raise ValueError("categories must be non-empty")
    cat_set = set(categories)
    if len(cat_set) != len(categories):
        raise ValueError("categories must not contain duplicates")
    if len(labels_a) != len(labels_b):
        raise ValueError(f"label length mismatch: {len(labels_a)} vs {len(labels_b)}")
    if not labels_a:
        raise ValueError("cannot evaluate empty label sequences")
    bad_a = sorted({lab for lab in labels_a if lab not in cat_set})
    bad_b = sorted({lab for lab in labels_b if lab not in cat_set})
    if bad_a or bad_b:
        raise ValueError(f"out-of-vocabulary labels: a={bad_a}, b={bad_b}")
    return cat_set


def cohens_kappa(
    labels_a: Sequence[str],
    labels_b: Sequence[str],
    categories: Sequence[str] = DEFAULT_LABELS,
) -> float:
    """Compute unweighted Cohen's kappa between two aligned label sequences.

    Args:
        labels_a: First rater's labels (or gold reference).
        labels_b: Second rater's labels (or model predictions).
        categories: Complete list of distinct label categories.

    Returns:
        Cohen's kappa in [-1.0, 1.0]. Returns 1.0 when both raters agree on
        every item even if only one category appears.

    Raises:
        ValueError: When sequences are empty, differ in length, contain
            unknown labels, or ``categories`` has duplicates.
    """
    _validate_inputs(labels_a, labels_b, categories)
    n = len(labels_a)
    agree = sum(1 for a, b in zip(labels_a, labels_b) if a == b)
    p_o = agree / n

    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    p_e = sum((counts_a[cat] / n) * (counts_b[cat] / n) for cat in categories)

    if abs(1.0 - p_e) < 1e-12:
        return 1.0 if agree == n else 0.0
    return (p_o - p_e) / (1.0 - p_e)


def confusion_matrix(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    categories: Sequence[str] = DEFAULT_LABELS,
) -> Dict[str, Dict[str, int]]:
    """Build a nested confusion matrix ``matrix[true_label][pred_label]``."""
    _validate_inputs(y_true, y_pred, categories)
    matrix: Dict[str, Dict[str, int]] = {
        cat: {pred: 0 for pred in categories} for cat in categories
    }
    for true_label, pred_label in zip(y_true, y_pred):
        matrix[true_label][pred_label] += 1
    return matrix


def classification_metrics(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    categories: Sequence[str] = DEFAULT_LABELS,
) -> Dict[str, Any]:
    """Compute accuracy, correction rate, Cohen's kappa, per-class F1, and macro-F1.

    Args:
        y_true: Reference labels (e.g. human adjudicated gold or Annotator A).
        y_pred: Comparison labels (e.g. LLM draft or Annotator B).
        categories: Distinct label vocabulary order.

    Returns:
        Dictionary of summary metrics, per-class precision/recall/F1/support,
        and full confusion matrix.
    """
    _validate_inputs(y_true, y_pred, categories)
    n = len(y_true)
    matrix = confusion_matrix(y_true, y_pred, categories)
    agree = sum(1 for a, b in zip(y_true, y_pred) if a == b)
    accuracy = agree / n

    per_class: Dict[str, Dict[str, Any]] = {}
    present_f1s: List[float] = []
    all_f1s: List[float] = []
    weighted_f1_num = 0.0

    for cat in categories:
        tp = matrix[cat][cat]
        fn = sum(matrix[cat][other] for other in categories if other != cat)
        fp = sum(matrix[other][cat] for other in categories if other != cat)
        support = tp + fn
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / support if support > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        per_class[cat] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
            "predicted": tp + fp,
        }
        all_f1s.append(f1)
        if support > 0 or (tp + fp) > 0:
            present_f1s.append(f1)
        weighted_f1_num += f1 * support

    return {
        "n": n,
        "agreements": agree,
        "disagreements": n - agree,
        "accuracy": round(accuracy, 4),
        "disagreement_rate": round(1.0 - accuracy, 4),
        "cohens_kappa": round(cohens_kappa(y_true, y_pred, categories), 4),
        "macro_f1_present": round(sum(present_f1s) / len(present_f1s), 4) if present_f1s else 0.0,
        "macro_f1_all": round(sum(all_f1s) / len(all_f1s), 4),
        "weighted_f1": round(weighted_f1_num / n, 4),
        "per_class": per_class,
        "confusion_matrix": matrix,
    }


def _index_rows(
    records: Iterable[Mapping[str, Any]],
    label_col: str,
    side: str,
) -> Dict[Tuple[str, str], Mapping[str, Any]]:
    """Index annotation rows by ``(case_id, sentence_id)`` with strict key/column checks."""
    indexed: Dict[Tuple[str, str], Mapping[str, Any]] = {}
    for row_num, row in enumerate(records, start=1):
        if label_col not in row:
            raise ValueError(f"side {side} row {row_num}: missing label column {label_col!r}")
        raw_cid = row.get("case_id")
        raw_sid = row.get("sentence_id")
        if not isinstance(raw_cid, str) or not raw_cid.strip():
            raise ValueError(f"side {side} row {row_num}: missing non-empty case_id")
        if not isinstance(raw_sid, str) or not raw_sid.strip():
            raise ValueError(f"side {side} row {row_num}: missing non-empty sentence_id")
        key = (raw_cid.strip(), raw_sid.strip())
        if key in indexed:
            raise ValueError(f"side {side}: duplicate key {key}")
        indexed[key] = row
    return indexed


def evaluate_aligned_records(
    records_a: Iterable[Mapping[str, Any]],
    records_b: Iterable[Mapping[str, Any]],
    col_a: str,
    col_b: str,
    by_jurisdiction: bool = False,
) -> Dict[str, Any]:
    """Join two annotation tables on ``(case_id, sentence_id)`` and score agreement.

    Rows where either label is empty are skipped and counted under ``unlabeled_skipped``.

    Raises:
        ValueError: When a required column or key is missing, duplicate keys
            appear, a non-empty label is outside ``ARGUMENT_ROLES``, or no
            overlapping labeled pairs exist.
    """
    map_a = _index_rows(records_a, col_a, "A")
    map_b = _index_rows(records_b, col_b, "B")

    keys_a = set(map_a)
    keys_b = set(map_b)
    common_keys = sorted(keys_a & keys_b)
    only_in_a = len(keys_a - keys_b)
    only_in_b = len(keys_b - keys_a)

    y_a: List[str] = []
    y_b: List[str] = []
    jurisdictions: List[str] = []
    disagreements: List[Dict[str, Any]] = []
    unlabeled = 0

    for key in common_keys:
        row_a = map_a[key]
        row_b = map_b[key]
        val_a = str(row_a[col_a] or "").strip().upper()
        val_b = str(row_b[col_b] or "").strip().upper()
        if not val_a or not val_b:
            unlabeled += 1
            continue
        if val_a not in ARGUMENT_ROLES:
            raise ValueError(f"{key}: unknown label {val_a!r} in column {col_a!r}")
        if val_b not in ARGUMENT_ROLES:
            raise ValueError(f"{key}: unknown label {val_b!r} in column {col_b!r}")
        y_a.append(val_a)
        y_b.append(val_b)
        jur = str(row_a.get("jurisdiction") or row_b.get("jurisdiction") or "UNKNOWN").strip()
        jurisdictions.append(jur)
        if val_a != val_b:
            disagreements.append({
                "case_id": key[0],
                "sentence_id": key[1],
                "jurisdiction": jur,
                "label_a": val_a,
                "label_b": val_b,
                "text": str(row_a.get("text") or row_b.get("text") or ""),
            })

    if not y_a:
        raise ValueError(
            f"no overlapping labeled rows found (common={len(common_keys)}, unlabeled={unlabeled})"
        )

    result: Dict[str, Any] = {
        "common_rows": len(common_keys),
        "only_in_a": only_in_a,
        "only_in_b": only_in_b,
        "unlabeled_skipped": unlabeled,
        "overall": classification_metrics(y_a, y_b),
        "disagreements": disagreements,
    }
    if by_jurisdiction:
        per_j: Dict[str, Any] = {}
        for jur in sorted(set(jurisdictions)):
            ja = [a for a, j in zip(y_a, jurisdictions) if j == jur]
            jb = [b for b, j in zip(y_b, jurisdictions) if j == jur]
            per_j[jur] = classification_metrics(ja, jb)
        result["by_jurisdiction"] = per_j
    return result
