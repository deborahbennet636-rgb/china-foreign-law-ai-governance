"""Full-text search and article-label resolution for the query layer.

Two jobs that share one rule: when unsure, refuse.

* An article label is read only if it has one of a closed set of shapes
  (第七条, （七）, Article 7, Sec. 7., or a bare 7). Anything else, such as
  Article 4a, Recital 27 or 第十二条第1款, is refused rather than mapped to
  the article that happens to carry the same number: returning the wrong
  article as if it were verbatim is the worst mistake this layer can make.
* Search reports which field matched and whether that field is source text.
  Snippets are cut from the stored text itself, so a snippet marked verbatim
  is a substring of what the database holds.
"""
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .splitter import cn_number

Record = Dict[str, Any]
Part = Tuple[str, Any, bool]  # field name, value, whether the value is source text

MIN_QUERY_CHARS = 2
SNIPPET_RADIUS = 40
SEARCH_SCOPES = ("all", "provision", "obligation", "case", "issue", "countermeasure")

_CN_DIGITS = "零一二三四五六七八九"
_CN_NUM = "零〇一二三四五六七八九十百千"
_LABEL = re.compile(
    rf"^(?:第(?P<article_cn>[{_CN_NUM}]+|\d+)条"
    rf"|\((?P<point>[{_CN_NUM}]+|\d+)\)"
    r"|(?:article|art\.?)(?P<article>\d+)"
    r"|(?:section|sec\.?)(?P<section>\d+)\.?"
    r"|(?P<bare>\d+))$"
)
# 第七条 and Article 7 are the same kind of unit in different languages.
_KIND = {"article_cn": "article", "article": "article", "point": "point", "section": "section"}


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


def _number(raw: str) -> Optional[int]:
    """Read digits, or a Chinese numeral written the standard way."""
    if raw.isdigit():
        return int(raw)
    try:
        number = cn_number(raw)
    except ValueError:
        return None
    # cn_number reads 一二 as 2 and 十十 as 20; only the standard spelling counts.
    return number if 0 < number < 10000 and to_cn_numeral(number) == raw.replace("〇", "零") else None


def parse_label(label: str) -> Optional[Tuple[Optional[str], int]]:
    """Return (kind, number) for a label, or None if its shape is not accepted.

    Kind is ``article``, ``point`` or ``section``, or None for a bare number.
    """
    flat = "".join(unicodedata.normalize("NFKC", label).split()).casefold()
    match = _LABEL.match(flat)
    if not match:
        return None
    group = next(name for name, value in match.groupdict().items() if value is not None)
    number = _number(match.group(group))
    if number is None:
        return None
    return _KIND.get(group), number


def label_number(label: str) -> Optional[int]:
    """Return the number a label names, or None when its shape is refused."""
    parsed = parse_label(label)
    return parsed[1] if parsed else None


def resolve_label(labels: List[str], wanted: Any) -> Tuple[Optional[str], List[str]]:
    """Find the one label of an instrument that ``wanted`` refers to.

    A bare number matches an article of any kind; a typed label matches only
    articles of the same kind. No match, several matches or an unaccepted
    shape all return None, with the closest labels for the error message.
    """
    wanted = str(wanted)  # an article may be given as the number 50
    target = "".join(unicodedata.normalize("NFKC", wanted).split()).casefold()
    for label in labels:
        if "".join(unicodedata.normalize("NFKC", label).split()).casefold() == target:
            return label, []
    request = parse_label(wanted)
    if request is None:
        return None, labels[:10]
    kind, number = request
    parsed = {label: parse_label(label) for label in labels}
    same = [label for label, item in parsed.items()
            if item is not None and item[1] == number and (kind is None or item[0] == kind)]
    if len(same) == 1:
        return same[0], []
    if same:
        return None, same
    numbered = sorted((label for label, item in parsed.items() if item is not None),
                      key=lambda label: abs(parsed[label][1] - number))
    return None, numbered[:6]


# ---- search ----

def fold_with_map(text: str) -> Tuple[str, List[int]]:
    """Fold width, case and whitespace, keeping each character's position in ``text``."""
    chars: List[str] = []
    origin: List[int] = []
    for position, char in enumerate(text):
        for piece in unicodedata.normalize("NFKC", char):
            if piece.isspace():
                continue
            for lowered in piece.lower():
                chars.append(lowered)
                origin.append(position)
    return "".join(chars), origin


def _fold(text: str) -> str:
    return fold_with_map(text)[0]


def snippet(text: str, needle: str) -> Optional[str]:
    """Cut the stored text around the first match of an already folded needle."""
    folded, origin = fold_with_map(text)
    start = folded.find(needle)
    if start < 0:
        return None
    first, last = origin[start], origin[start + len(needle) - 1]
    begin, end = max(0, first - SNIPPET_RADIUS), min(len(text), last + 1 + SNIPPET_RADIUS)
    return text[begin:end]


def _first_match(needle: str, parts: Iterable[Part]) -> Optional[Record]:
    """Return where ``needle`` first occurs among the parts, or None."""
    for field, value, verbatim in parts:
        if not value:
            continue
        cut = snippet(str(value), needle)
        if cut is not None:
            return {"matched_field": field, "verbatim": verbatim, "snippet": cut,
                    "snippet_cut": len(cut) < len(str(value))}
    return None


def _parts(dataset: Record, kinds: set) -> Iterable[Tuple[Record, Iterable[Part]]]:
    """Yield, for every record of the wanted kinds, its hit header and searchable parts."""
    if "provision" in kinds:
        for item in dataset["instruments"]:
            for provision in item["provisions"]:
                yield ({"kind": "provision", "ref": f"{item['id']}#{provision['no']}",
                        "title": f"{item['short_title']} {provision['no']}"},
                       [("text", provision.get("text"), True), ("heading", provision.get("heading"), True)])
    if "obligation" in kinds:
        for item in dataset["obligations"]:
            yield ({"kind": "obligation", "ref": item["id"], "title": f"{item['instrument_id']}#{item['provision']}"},
                   [("quote", item.get("quote"), True), ("duty", item.get("duty"), False),
                    ("trigger", item.get("trigger"), False)])
    if "case" in kinds:
        for item in dataset["cases"]:
            parts: List[Part] = [("caption", item.get("caption"), True),
                                 ("case_numbers", " ".join(item.get("case_numbers", [])), True)]
            parts += [(f"excerpt:{e['kind']}", e["text"], True) for e in item.get("excerpts", [])]
            parts.append(("short_name", item.get("short_name"), False))
            yield {"kind": "case", "ref": item["id"], "title": item["short_name"]}, parts
    if "issue" in kinds:
        for item in dataset["issues"]:
            comparable = (item.get("comparison") or {}).get("comparable")
            parts = [("title", item.get("title"), False), ("question", item.get("question"), False),
                     ("editor_note", item.get("editor_note"), False)]
            parts += [(f"summary:{p['jurisdiction']}", p.get("summary"), False) for p in item.get("positions", [])]
            yield {"kind": "issue", "ref": item["id"], "title": item["title"], "comparable": comparable}, parts
    if "countermeasure" in kinds:
        for item in dataset["countermeasures"]:
            yield ({"kind": "countermeasure", "direction": item.get("direction"), "ref": item["id"],
                    "title": item["title"]},
                   [("title", item.get("title"), True), ("target", item.get("target"), False),
                    ("issuer", item.get("issuer"), False), ("note", item.get("note"), False)])


def search(dataset: Record, query: str, scope: str = "all", limit: int = 20) -> Record:
    """Search every layer of the database for ``query``.

    Raises:
        ValueError: When the query is shorter than two characters once
            whitespace is removed, or the scope is unknown.
    """
    needle = _fold(query)
    if len(needle) < MIN_QUERY_CHARS:
        raise ValueError("query must have at least 2 characters once spaces are removed")
    if scope not in SEARCH_SCOPES:
        raise ValueError(f"scope must be one of {list(SEARCH_SCOPES)}")
    kinds = set(SEARCH_SCOPES[1:]) if scope == "all" else {scope}
    hits: List[Record] = []
    for header, parts in _parts(dataset, kinds):
        found = _first_match(needle, parts)
        if found is not None:
            hits.append({**header, **found})
    return {
        "query": query,
        "scope": scope,
        "total": len(hits),
        "returned": min(len(hits), limit),
        "hits": hits[:limit],
        "note": ("没有命中只说明本库没有收，不说明不存在。" if not hits else
                 "命中按库内顺序排列，不按相关度排序。verbatim 为 false 的片段是编者撰写的文字，不是原文；"
                 "countermeasure 命中按 direction 区分境外对华与中国对外，不可合并解读。"),
    }
