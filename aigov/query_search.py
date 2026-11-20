"""Full-text search and article-label resolution for the query layer.

Search folds width and whitespace the way the viewer does, so a query typed
with or without spaces, in full-width or half-width characters, finds the
same text. It ranks nothing: hits come back grouped by kind, in database
order, because a relevance score would be one more judgement nobody checked.
"""
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from .splitter import cn_number
from .textnorm import fold

Record = Dict[str, Any]

MIN_QUERY_CHARS = 2
SNIPPET_RADIUS = 40
SEARCH_SCOPES = ("all", "provision", "obligation", "case", "issue", "countermeasure")

_CN_LABEL = re.compile(r"^(?:第|\()([零〇一二三四五六七八九十百千]+)(?:条|\))$")
_ARABIC = re.compile(r"\d+")
_CN_DIGITS = "零一二三四五六七八九"


def to_cn_numeral(number: int) -> str:
    """Write 1..9999 the way Chinese statutes number their articles.

    105 is 一百零五, 110 is 一百一十, 10 is 十, 1010 is 一千零一十.
    """
    if not 0 < number < 10000:
        raise ValueError(f"article number out of range: {number}")
    if number < 10:
        return _CN_DIGITS[number]
    if number < 20:
        return "十" + (_CN_DIGITS[number % 10] if number % 10 else "")
    parts: List[str] = []
    pending_zero = started = False
    for value, unit in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
        digit = number // value % 10
        if digit == 0:
            pending_zero = pending_zero or started
            continue
        if pending_zero:
            parts.append("零")
            pending_zero = False
        parts.append(_CN_DIGITS[digit] + unit)
        started = True
    return "".join(parts)


def label_number(label: str) -> Optional[int]:
    """Return the article number a label names, or None.

    Reads 第七条, （七）, Article 7, Sec. 7., 7 and 第7条 alike. A label such
    as 第七条之一 names a different article and yields None.
    """
    flat = "".join(unicodedata.normalize("NFKC", label).split())
    match = _CN_LABEL.match(flat)
    if match:
        try:
            return cn_number(match.group(1))
        except ValueError:
            return None
    if "之" in flat:
        return None
    digits = _ARABIC.findall(flat)
    return int(digits[0]) if len(digits) == 1 else None


def resolve_label(labels: List[str], wanted: str) -> Tuple[Optional[str], List[str]]:
    """Find the label of an instrument that ``wanted`` refers to.

    Args:
        labels: Every provision label of the instrument, in order.
        wanted: The label as typed by the caller.

    Returns:
        The matching label (or None) and, when there is no single match,
        the labels that came closest, for the error message.
    """
    target = "".join(unicodedata.normalize("NFKC", wanted).split())
    for label in labels:
        if "".join(unicodedata.normalize("NFKC", label).split()) == target:
            return label, []
    number = label_number(wanted)
    if number is None:
        return None, labels[:10]
    same = [label for label in labels if label_number(label) == number]
    if len(same) == 1:
        return same[0], []
    if same:
        return None, same
    numbered = sorted(
        (label for label in labels if label_number(label) is not None),
        key=lambda label: abs((label_number(label) or 0) - number),
    )
    return None, numbered[:6]


def _snippet(text: str, needle: str) -> str:
    """Cut a short stretch of ``text`` around the first match of ``needle``."""
    folded = fold(text)
    lowered = folded.text.lower()
    start = lowered.find(needle)
    if start < 0 or len(lowered) != len(folded.text):
        return text[: SNIPPET_RADIUS * 2] + ("…" if len(text) > SNIPPET_RADIUS * 2 else "")
    first = folded.offsets[start]
    last = folded.offsets[start + len(needle) - 1]
    begin = max(0, first - SNIPPET_RADIUS)
    end = min(len(folded.source), last + 1 + SNIPPET_RADIUS)
    body = folded.source[begin:end].replace("\n", " ")
    return ("…" if begin else "") + body + ("…" if end < len(folded.source) else "")


def _matches(needle: str, *parts: Any) -> Optional[str]:
    """Return the first part that contains ``needle``, or None."""
    for part in parts:
        if part and needle in fold(str(part)).text.lower():
            return str(part)
    return None


def search(dataset: Record, query: str, scope: str = "all", limit: int = 20) -> Record:
    """Search every layer of the database for ``query``.

    Raises:
        ValueError: When the query is shorter than two characters once
            whitespace is removed, or the scope is unknown.
    """
    needle = fold(query).text.lower()
    if len(needle) < MIN_QUERY_CHARS:
        raise ValueError("query must have at least 2 characters once spaces are removed")
    if scope not in SEARCH_SCOPES:
        raise ValueError(f"scope must be one of {list(SEARCH_SCOPES)}")
    wanted = set(SEARCH_SCOPES[1:]) if scope == "all" else {scope}
    hits: List[Record] = []

    def add(kind: str, ref: str, title: str, text: Optional[str]) -> None:
        if text is not None:
            hits.append({"kind": kind, "ref": ref, "title": title, "snippet": _snippet(text, needle)})

    if "provision" in wanted:
        for item in dataset["instruments"]:
            for provision in item["provisions"]:
                add("provision", f"{item['id']}#{provision['no']}", f"{item['short_title']} {provision['no']}",
                    _matches(needle, provision.get("text"), provision.get("heading")))
    if "obligation" in wanted:
        for item in dataset["obligations"]:
            add("obligation", item["id"], f"{item['instrument_id']}#{item['provision']}",
                _matches(needle, item.get("quote"), item.get("duty"), item.get("trigger")))
    if "case" in wanted:
        for item in dataset["cases"]:
            add("case", item["id"], item["short_name"],
                _matches(needle, item.get("caption"), item.get("short_name"), " ".join(item.get("case_numbers", [])),
                         *(excerpt["text"] for excerpt in item.get("excerpts", []))))
    if "issue" in wanted:
        for item in dataset["issues"]:
            add("issue", item["id"], item["title"],
                _matches(needle, item.get("title"), item.get("question"), item.get("editor_note"),
                         *(position.get("summary") for position in item.get("positions", []))))
    if "countermeasure" in wanted:
        for item in dataset["countermeasures"]:
            add("countermeasure", item["id"], item["title"],
                _matches(needle, item.get("title"), item.get("target"), item.get("issuer"), item.get("note")))
    return {
        "query": query,
        "scope": scope,
        "total": len(hits),
        "returned": min(len(hits), limit),
        "hits": hits[:limit],
        "note": "没有命中只说明本库没有收，不说明不存在。" if not hits else "命中按库内顺序排列，不按相关度排序。",
    }
