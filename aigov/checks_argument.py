"""Checks on sentence-level legal argument annotations (LAMUS FIRAC pilot).

Every annotated sentence must satisfy two invariants:

* Each sentence matches ``case.excerpts[excerpt_index].text`` sequentially on
  word boundaries with word spaces preserved (``keep_word_spaces=True``), so
  corrupted spacing, mid-word splits, and out-of-order excerpts are rejected.
* Every excerpt of the case is reconstructed in full with zero dropped or
  fabricated characters when ``complete_excerpts`` is true.

The FIRAC ``role`` and ``rationale`` are editorial or LLM-draft judgements, so
``annotation_mode`` must explicitly state whether human verification has taken
place.
"""
from collections import defaultdict
from typing import Any, Dict, List, Mapping, Set

from .config import ANNOTATION_MODES, ARGUMENT_ROLES
from .textnorm import Folded, fold, normalize

Record = Dict[str, Any]

MAX_RATIONALE_CHARS = 200


def _is_word_char(char: str) -> bool:
    """Match ``textnorm._is_word_char``: ASCII letter or digit."""
    return char.isascii() and char.isalnum()


def _on_word_boundaries(haystack: Folded, start: int, length: int) -> bool:
    """Check that ``haystack.text[start:start+length]`` begins and ends on word boundaries."""
    first = haystack.offsets[start]
    last = haystack.offsets[start + length - 1]
    source = haystack.source
    if _is_word_char(source[first]) and first > 0 and _is_word_char(source[first - 1]):
        return False
    if _is_word_char(source[last]) and last + 1 < len(source) and _is_word_char(source[last + 1]):
        return False
    return True


def _check_excerpt_sequence(
    owner: str,
    ex_idx: int,
    excerpt_text: str,
    pieces: List[str],
) -> List[str]:
    """Verify that ``pieces`` tile ``excerpt_text`` sequentially on word boundaries."""
    folded = fold(excerpt_text, ignore_case=False, keep_word_spaces=True)
    cursor = 0
    total = len(folded.text)

    for step, raw_piece in enumerate(pieces):
        while cursor < total and folded.text[cursor] == " ":
            cursor += 1
        needle = fold(raw_piece, ignore_case=False, keep_word_spaces=True).text
        if not needle:
            return [f"{owner}/excerpt[{ex_idx}]: sentence #{step + 1} is empty"]
        if not folded.text.startswith(needle, cursor):
            return [
                f"{owner}/excerpt[{ex_idx}]: sentence #{step + 1} does not match excerpt text "
                f"verbatim in sequence (spacing or text mismatch)"
            ]
        if not _on_word_boundaries(folded, cursor, len(needle)):
            return [
                f"{owner}/excerpt[{ex_idx}]: sentence #{step + 1} splits inside a Latin word or number"
            ]
        cursor += len(needle)

    while cursor < total and folded.text[cursor] == " ":
        cursor += 1
    if cursor != total:
        return [
            f"{owner}/excerpt[{ex_idx}]: concatenated sentences do not reconstruct full excerpt verbatim"
        ]
    return []


def check_argument_record(
    record: Record,
    cases_by_id: Mapping[str, Record],
    provision_refs: Set[str],
) -> List[str]:
    """Validate one case's sentence-level argument annotation file.

    Args:
        record: Parsed JSON record from ``data/arguments/``.
        cases_by_id: Every case record in the database, keyed by case id.
        provision_refs: Valid ``instrument_id#provision`` references.

    Returns:
        One message per problem found; empty list means valid.
    """
    raw_id = record.get("id")
    owner = raw_id.strip() if isinstance(raw_id, str) and raw_id.strip() else "?"
    errors: List[str] = []

    if owner == "?":
        errors.append("?: argument record is missing a non-empty string id")

    case_id = record.get("case_id")
    case = cases_by_id.get(case_id) if isinstance(case_id, str) else None
    if case is None:
        return errors + [f"{owner}: unknown case_id {case_id!r}"]

    mode = record.get("annotation_mode")
    if mode not in ANNOTATION_MODES:
        errors.append(f"{owner}: unknown annotation_mode {mode!r}")

    annotator = record.get("annotator")
    if not isinstance(annotator, str) or not annotator.strip():
        errors.append(f"{owner}: missing non-empty annotator identifier")

    complete_excerpts = record.get("complete_excerpts", True)
    if not isinstance(complete_excerpts, bool):
        errors.append(f"{owner}: complete_excerpts must be a boolean")
        complete_excerpts = True

    sentences = record.get("sentences")
    if not isinstance(sentences, list) or not sentences:
        return errors + [f"{owner}: sentences must be a non-empty list"]

    excerpts = case.get("excerpts", [])
    seen_ids: Set[str] = set()
    by_excerpt: Dict[int, List[str]] = defaultdict(list)
    prev_ex_idx = -1

    for idx, item in enumerate(sentences):
        if not isinstance(item, dict):
            errors.append(f"{owner}/[{idx}]: sentence entry must be an object")
            continue

        sid = item.get("id")
        where = f"{owner}/{sid.strip() if isinstance(sid, str) and sid.strip() else idx}"
        if not isinstance(sid, str) or not sid.strip():
            errors.append(f"{where}: sentence is missing non-empty string id")
        elif sid in seen_ids:
            errors.append(f"{where}: duplicate sentence id {sid!r}")
        else:
            seen_ids.add(sid)

        ex_idx = item.get("excerpt_index")
        if isinstance(ex_idx, bool) or not isinstance(ex_idx, int) or ex_idx < 0 or ex_idx >= len(excerpts):
            errors.append(f"{where}: excerpt_index {ex_idx!r} out of range (0..{len(excerpts) - 1})")
            continue
        if ex_idx < prev_ex_idx:
            errors.append(
                f"{where}: excerpt_index {ex_idx} appears after {prev_ex_idx}; "
                f"sentences must follow excerpt order"
            )
        else:
            prev_ex_idx = ex_idx

        excerpt = excerpts[ex_idx]
        if item.get("source_id") != excerpt.get("source_id"):
            errors.append(
                f"{where}: source_id {item.get('source_id')!r} does not match excerpt[{ex_idx}] "
                f"source_id {excerpt.get('source_id')!r}"
            )

        role = item.get("role")
        if role not in ARGUMENT_ROLES:
            errors.append(f"{where}: unknown FIRAC role {role!r}")

        text = item.get("text")
        if not isinstance(text, str) or not normalize(text):
            errors.append(f"{where}: sentence text is empty")
        else:
            by_excerpt[ex_idx].append(text)

        rationale = item.get("rationale")
        if rationale is not None:
            if not isinstance(rationale, str):
                errors.append(f"{where}: rationale must be a string")
            elif len(normalize(rationale)) > MAX_RATIONALE_CHARS:
                errors.append(f"{where}: rationale exceeds {MAX_RATIONALE_CHARS} characters")

        if "provisions_mentioned" in item:
            provs = item["provisions_mentioned"]
            if not isinstance(provs, list) or not all(isinstance(p, str) for p in provs):
                errors.append(f"{where}: provisions_mentioned must be a list of strings")
            else:
                for ref in provs:
                    if ref not in provision_refs:
                        errors.append(f"{where}: unknown provision reference {ref!r}")

    if complete_excerpts:
        missing = [i for i in range(len(excerpts)) if i not in by_excerpt]
        if missing:
            errors.append(f"{owner}: complete_excerpts is true but excerpts {missing} have no sentences")

    for ex_idx, pieces in sorted(by_excerpt.items()):
        errors.extend(_check_excerpt_sequence(owner, ex_idx, excerpts[ex_idx]["text"], pieces))

    return errors
