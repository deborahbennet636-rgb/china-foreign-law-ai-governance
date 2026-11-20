"""Turn saved pages into text, and compare quotes with their source verbatim.

Two different jobs live here on purpose:

* ``html_to_text`` keeps line structure, because the splitters need it.
* ``fold`` and ``occurs`` throw whitespace away, because a quote must match
  its source no matter how a page wraps its lines or how a PDF text layer
  spaces its letters.

Dropping whitespace joins Latin words together, so ``occurs`` also checks
that a match starts and ends where a word starts and ends in the source.
Without that, "lawful" would be found inside "unlawful".
"""
import html
import re
import unicodedata
from dataclasses import dataclass
from typing import List, Tuple

NORMALIZER_VERSION = "nfkc-wordspace-wordbound/3"

_DROP_BLOCKS = re.compile(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>")
_COMMENTS = re.compile(r"(?s)<!--.*?-->")
_BREAKS = re.compile(r"(?i)<(br|/p|/div|/tr|/li|/h[1-6]|/table|/section|/article)\b[^>]*>")
_TAGS = re.compile(r"<[^>]+>")
_INLINE_SPACE = re.compile(r"[ \t\r\f\v 　]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")


@dataclass(frozen=True)
class Folded:
    """A text prepared for verbatim matching.

    Attributes:
        source: The text after NFKC folding, whitespace kept.
        text: ``source`` with all whitespace removed.
        offsets: For each character of ``text``, its position in ``source``.
    """

    source: str
    text: str
    offsets: Tuple[int, ...]


def html_to_text(markup: str) -> str:
    """Strip markup from a saved HTML page while keeping paragraph breaks.

    Args:
        markup: Raw HTML as saved in ``data/raw``.

    Returns:
        Plain text with one paragraph per line.
    """
    text = _DROP_BLOCKS.sub(" ", markup)
    text = _COMMENTS.sub(" ", text)
    text = _BREAKS.sub("\n", text)
    text = _TAGS.sub("", text)
    text = html.unescape(text)
    text = _INLINE_SPACE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    return _BLANK_LINES.sub("\n", "\n".join(lines)).strip()


def fold(text: str, ignore_case: bool = False, keep_word_spaces: bool = False) -> Folded:
    """Prepare a text for matching.

    NFKC folds full-width and half-width variants together. Nothing else is
    touched: punctuation and wording must match exactly.

    Args:
        text: The text to prepare.
        ignore_case: Fold letter case; for titles a source prints in capitals.
        keep_word_spaces: Keep one space where whitespace separates two Latin
            letters or digits, so that words cannot be re-divided ("a part"
            does not match "apart"). Off for PDF text layers, whose spacing
            inside words is unreliable.
    """
    source = unicodedata.normalize("NFKC", text)
    if ignore_case:
        source = source.casefold()
    kept: List[Tuple[int, str]] = []
    gap = -1
    for index, char in enumerate(source):
        if char.isspace():
            gap = index if gap < 0 else gap
            continue
        if gap >= 0 and keep_word_spaces and kept and _is_word_char(kept[-1][1]) and _is_word_char(char):
            kept.append((gap, " "))
        gap = -1
        kept.append((index, char))
    return Folded(source, "".join(char for _, char in kept), tuple(index for index, _ in kept))


def normalize(text: str) -> str:
    """Return ``text`` NFKC-folded with all whitespace removed."""
    return fold(text).text


def _is_word_char(char: str) -> bool:
    """Tell whether ``char`` is an ASCII letter or digit."""
    return char.isascii() and char.isalnum()


def _on_word_boundaries(haystack: Folded, start: int, length: int) -> bool:
    """Check that a match does not begin or end inside a Latin word or number."""
    first = haystack.offsets[start]
    last = haystack.offsets[start + length - 1]
    source = haystack.source
    if _is_word_char(source[first]) and first > 0 and _is_word_char(source[first - 1]):
        return False
    if _is_word_char(source[last]) and last + 1 < len(source) and _is_word_char(source[last + 1]):
        return False
    return True


def occurs(haystack: Folded, quote: str, ignore_case: bool = False, keep_word_spaces: bool = False) -> bool:
    """Tell whether ``quote`` appears verbatim in ``haystack``.

    Args:
        haystack: The folded source text.
        quote: The text claimed to come from that source.
        ignore_case: Must equal the setting ``haystack`` was folded with.
        keep_word_spaces: Must equal the setting ``haystack`` was folded with.

    Returns:
        True when the quote occurs in the source and the occurrence starts
        and ends on word boundaries.
    """
    needle = fold(quote, ignore_case, keep_word_spaces).text
    if not needle:
        return False
    start = haystack.text.find(needle)
    while start >= 0:
        if _on_word_boundaries(haystack, start, len(needle)):
            return True
        start = haystack.text.find(needle, start + 1)
    return False
