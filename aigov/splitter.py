"""Split the text of an instrument into numbered provisions.

Each drafting style gets one splitter, registered by name. A splitter only
cuts text; it never rewrites it, so every provision stays a verbatim slice
of the source and can be checked against the snapshot afterwards.
"""
import logging
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Pattern

logger = logging.getLogger(__name__)

Provision = Dict[str, object]
Splitter = Callable[[List[str]], List[Provision]]

SPLITTER_REGISTRY: Dict[str, Splitter] = {}

_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_NUM = "零〇一二三四五六七八九十百千"
_SENTENCE_END = ("。", "；", "：", "，", ".", ";", ":", ",")


def register_splitter(name: str) -> Callable[[Splitter], Splitter]:
    """Register a splitter under the name used in ingest specs."""

    def decorator(func: Splitter) -> Splitter:
        SPLITTER_REGISTRY[name] = func
        return func

    return decorator


def get_splitter(name: str) -> Splitter:
    """Look up a splitter.

    Raises:
        KeyError: When no splitter is registered under ``name``.
    """
    if name not in SPLITTER_REGISTRY:
        raise KeyError(f"no splitter named {name!r}; known: {sorted(SPLITTER_REGISTRY)}")
    return SPLITTER_REGISTRY[name]


def cn_number(text: str) -> int:
    """Convert a Chinese numeral below ten thousand to an integer.

    Args:
        text: A numeral such as ``二十四`` or ``一千一百九十七``.

    Returns:
        Its integer value.

    Raises:
        ValueError: When ``text`` is empty or holds a non-numeral character.
    """
    if not text:
        raise ValueError("empty Chinese numeral")
    total, current = 0, 0
    for char in text:
        if char in _CN_DIGITS:
            current = _CN_DIGITS[char]
        elif char in _CN_UNITS:
            total += (current or 1) * _CN_UNITS[char]
            current = 0
        else:
            raise ValueError(f"not a Chinese numeral: {text!r}")
    return total + current


@dataclass(frozen=True)
class _Style:
    """Line patterns that define one drafting style."""

    heading: Pattern[str]  # group 1: the label, group 2: the number, group 3: rest of line
    division: Optional[Pattern[str]] = None  # chapter or part heading
    subdivision: Optional[Pattern[str]] = None  # section heading inside a chapter
    chinese_numbers: bool = False
    title_on_next_line: bool = False  # the line after the label is the provision's title


def _split(lines: List[str], style: _Style) -> List[Provision]:
    """Cut lines into provisions according to a style."""
    provisions: List[Provision] = []
    division, subdivision = "", ""
    current: Optional[Provision] = None
    body: List[str] = []

    def close() -> None:
        if current is None:
            return
        parts = [part for part in body if part]
        if style.title_on_next_line and parts:
            current["heading"] = parts.pop(0)
        current["text"] = "\n".join(parts)
        provisions.append(current)

    for line in lines:
        # A heading names a part; it is not a sentence. A body line that only
        # looks like one ("第三章 规定的情形除外。") ends in punctuation.
        heading_like = not line.rstrip().endswith(_SENTENCE_END)
        is_division = heading_like and style.division is not None and style.division.match(line)
        is_subdivision = heading_like and style.subdivision is not None and style.subdivision.match(line)
        if is_division or is_subdivision:
            close()
            current, body = None, []
            if is_division:
                division, subdivision = line, ""
            else:
                subdivision = line
            continue
        match = style.heading.match(line)
        if match:
            close()
            number = match.group(2)
            current = {
                "no": match.group(1),
                "ordinal": cn_number(number) if style.chinese_numbers else int(number),
                "division": " / ".join(part for part in (division, subdivision) if part),
            }
            body = [(match.group(3) or "").strip()]
            continue
        if current is not None:
            body.append(line)
    close()
    return provisions


@register_splitter("cn-article")
def split_cn_article(lines: List[str]) -> List[Provision]:
    """Chinese statutes and rules: ``第X条`` under optional ``第X章`` and ``第X节``.

    A heading must be followed by a space or end the line. A body sentence
    that merely begins with ``第三条规定`` or ``第三章规定`` is body text.
    """
    style = _Style(
        heading=re.compile(rf"^(第([{_CN_NUM}]+)条)(?:\s+(.*))?$"),
        division=re.compile(rf"^第[{_CN_NUM}]+[编章](?:\s|$)"),
        subdivision=re.compile(rf"^第[{_CN_NUM}]+节(?:\s|$)"),
        chinese_numbers=True,
    )
    return _split(lines, style)


@register_splitter("cn-point")
def split_cn_point(lines: List[str]) -> List[Provision]:
    """Chinese judicial and policy documents: ``（X）`` under ``X、`` parts."""
    style = _Style(
        heading=re.compile(rf"^(（([{_CN_NUM}]+)）)(.*)$"),
        division=re.compile(rf"^[{_CN_NUM}]+、"),
        chinese_numbers=True,
    )
    return _split(lines, style)


@register_splitter("eu-article")
def split_eu_article(lines: List[str]) -> List[Provision]:
    """EU regulations on EUR-Lex: ``Article N`` then its title, under chapters.

    Only fit for a regulation as adopted. An amending act quotes replaced
    articles inside its own articles, which this style cannot tell apart.
    """
    style = _Style(
        heading=re.compile(r"^(Article (\d+))()$"),
        division=re.compile(r"^CHAPTER [IVXLC]+$"),
        subdivision=re.compile(r"^SECTION \d+$"),
        title_on_next_line=True,
    )
    return _split(lines, style)


@register_splitter("us-publaw")
def split_us_publaw(lines: List[str]) -> List[Provision]:
    """US public laws as printed by GPO: ``SECTION 1.`` then ``SEC. N.``."""
    style = _Style(heading=re.compile(r"^((?:SECTION|SEC\.) (\d+)\.)(.*)$"))
    return _split(lines, style)


@register_splitter("us-code")
def split_us_code(lines: List[str]) -> List[Provision]:
    """Sections of the United States Code as GPO prints them: ``§107. Heading``.

    The section's catchline stands on the label's own line and becomes its
    heading. The source credit line that follows the text, ``(Pub. L. ...)``,
    is an editorial note of the Code and is cut off by the spec's
    ``end_before``, not by this splitter.
    """
    style = _Style(heading=re.compile(r"^(§(\d+)\.)\s+(.+)$"), title_on_next_line=True)
    return _split(lines, style)


@register_splitter("us-eo")
def split_us_eo(lines: List[str]) -> List[Provision]:
    """US executive orders in the Federal Register text: ``Section 1.``, ``Sec. N.``.

    The Federal Register text is indented with spaces, so lines are stripped
    first; whitespace does not take part in the verbatim comparison.
    """
    style = _Style(heading=re.compile(r"^((?:Section|Sec\.) (\d+)\.)(.*)$"))
    return _split([line.strip() for line in lines], style)


def slice_lines(text: str, start_at: Optional[str], end_before: Optional[str]) -> List[str]:
    """Return the lines of the instrument body.

    Args:
        text: Page text with one paragraph per line.
        start_at: Exact line that opens the body, or None to start at the
            top. When the line occurs more than once (page title, then
            document title) the last occurrence is used.
        end_before: Exact line that follows the body, searched after the
            start, or None to run to the end of the page.

    Returns:
        Lines from ``start_at`` (inclusive) to ``end_before`` (exclusive).

    Raises:
        ValueError: When a marker that was asked for is missing.
    """
    lines = text.split("\n")
    start = 0
    if start_at is not None:
        starts = [index for index, line in enumerate(lines) if line.strip() == start_at]
        if not starts:
            raise ValueError(f"start marker not found: {start_at!r}")
        start = starts[-1]
    if end_before is None:
        return lines[start:]
    for index in range(start + 1, len(lines)):
        if lines[index].strip() == end_before:
            return lines[start:index]
    raise ValueError(f"end marker not found after start: {end_before!r}")


def check_sequence(provisions: List[Provision], expected: int) -> None:
    """Fail unless provisions run 1..expected with no gap or repeat.

    Args:
        provisions: Output of a splitter.
        expected: Number of provisions the instrument is known to have.

    Raises:
        ValueError: When the count or the numbering is off.
    """
    ordinals = [int(str(item["ordinal"])) for item in provisions]
    if ordinals != list(range(1, expected + 1)):
        raise ValueError(f"expected provisions 1..{expected}, got {ordinals}")
    empty = [item["no"] for item in provisions if not item.get("text")]
    if empty:
        raise ValueError(f"provisions with no text: {empty}")


def select_provisions(provisions: List[Provision], wanted: List[str]) -> List[Provision]:
    """Keep only the named provisions of a general law.

    Args:
        provisions: Output of a splitter.
        wanted: Provision labels to keep, e.g. ``["第一千一百九十七条"]``.

    Returns:
        The selected provisions, in source order.

    Raises:
        ValueError: When a wanted provision is missing, repeated or empty.
    """
    keep = set(wanted)
    selected = [item for item in provisions if item["no"] in keep and item.get("text")]
    found = [str(item["no"]) for item in selected]
    if sorted(found) != sorted(keep):
        raise ValueError(f"wanted {sorted(keep)}, found {found}")
    return selected


def check_consecutive(provisions: List[Provision]) -> None:
    """Fail unless numbering rises by exactly one from provision to provision.

    Used when only some provisions of a long text are kept. A body line
    mistaken for a heading would cut the provision before it short without
    any other sign; it shows up here as a break in the numbering.

    Args:
        provisions: Every provision the splitter produced, before selection.

    Raises:
        ValueError: When the text yields no provision or numbering breaks.
    """
    ordinals = [int(str(item["ordinal"])) for item in provisions]
    if not ordinals:
        raise ValueError("no provisions found")
    breaks = [(a, b) for a, b in zip(ordinals, ordinals[1:]) if b != a + 1]
    if breaks:
        raise ValueError(f"numbering is not consecutive at {breaks[:5]}")
