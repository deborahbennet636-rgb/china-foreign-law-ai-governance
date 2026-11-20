"""Check quotes, dates and identifiers against registered snapshots."""
import datetime
import re
import unicodedata
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from .caseparse import clean_lines, extract_block
from .config import GRADE_BY_KIND, PARSED, PENDING, VERIFIED
from .sources import read_text
from .textnorm import Folded, fold, normalize, occurs

# A quote shorter than this proves nothing: it would match almost any page.
MIN_QUOTE_CHARS = 8
MIN_LATIN_QUOTE_CHARS = 16
_FIRST_CJK = 0x2E80
_NOT_ALNUM_BEFORE = r"(?<![0-9A-Za-z])"
# After a token: no letter or digit, no decimal continuation (§ 201 is not
# found in § 201.4, Sec. 4 not in Sec. 4.1), and no "之一"-style suffix,
# which would make a Chinese provision label name a different provision.
_NOT_CONTINUED = r"(?![0-9A-Za-z])(?!\.\d)(?!之[一二三四五六七八九十])"
_CN_DIGITS = "〇一二三四五六七八九"

_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

Scope = Mapping[str, str]


class SnapshotIndex:
    """Answers whether a quote occurs in a snapshot, or in one block of it."""

    def __init__(
        self,
        manifest: Mapping[str, Dict[str, Any]],
        loader: Callable[[Dict[str, Any]], str] = read_text,
    ) -> None:
        """Wrap a source manifest.

        Args:
            manifest: Source id mapped to its manifest entry.
            loader: Returns the plain text of a manifest entry. The default
                reads the snapshot from disk and checks its hash.
        """
        self._manifest = manifest
        self._loader = loader
        self._cache: Dict[Tuple[Any, ...], Folded] = {}

    def has(self, source_id: str) -> bool:
        """Return True when ``source_id`` is registered."""
        return source_id in self._manifest

    def entry(self, source_id: str) -> Dict[str, Any]:
        """Return the manifest entry of ``source_id``."""
        return self._manifest[source_id]

    def text(self, source_id: str) -> str:
        """Return the plain text of a snapshot."""
        return self._loader(self._manifest[source_id])

    def keeps_word_spaces(self, source_id: str) -> bool:
        """Tell whether word spacing in this source can be trusted.

        A PDF text layer splits and joins words arbitrarily, so for PDFs all
        whitespace is ignored. Everywhere else the space between two Latin
        words is kept, so that "a part" cannot be read as "apart".
        """
        return "text_file" not in self._manifest[source_id]

    def _folded(self, source_id: str, scope: Optional[Scope], ignore_case: bool) -> Folded:
        """Return the whole snapshot, or one block of it, ready for matching."""
        span = (scope["block_start"], scope["block_end"]) if scope else None
        key = (source_id, span, ignore_case)
        if key not in self._cache:
            text = self.text(source_id)
            if span:
                text = "\n".join(extract_block(clean_lines(text), span[0], span[1]))
            self._cache[key] = fold(text, ignore_case, self.keeps_word_spaces(source_id))
        return self._cache[key]

    def found(self, source_id: str, quote: str, scope: Optional[Scope] = None, ignore_case: bool = False) -> bool:
        """Return True when ``quote`` occurs verbatim in the snapshot.

        Args:
            source_id: The snapshot to look in.
            quote: The text claimed to come from it.
            scope: When given, only the block between ``block_start`` and
                ``block_end`` is searched. Court digest pages hold several
                cases, and a sentence about one must not vouch for another.
            ignore_case: Fold letter case; for titles printed in capitals.

        Returns:
            False for an unregistered source, an unreadable snapshot, a
            missing block, or no match.
        """
        if source_id not in self._manifest:
            return False
        try:
            folded = self._folded(source_id, scope, ignore_case)
            return occurs(folded, quote, ignore_case, self.keeps_word_spaces(source_id))
        except (ValueError, OSError):
            return False


def long_enough(quote: str) -> bool:
    """Tell whether a quote is long enough to count as evidence."""
    flat = normalize(quote)
    has_cjk = any(ord(char) >= _FIRST_CJK for char in flat)
    has_latin = any(char.isascii() and char.isalpha() for char in flat)
    return len(flat) >= (MIN_LATIN_QUOTE_CHARS if has_latin and not has_cjk else MIN_QUOTE_CHARS)


def _cn_numeral(number: int) -> str:
    """Write a number from 1 to 99 the way Chinese judgments write dates."""
    tens, ones = divmod(number, 10)
    head = "" if tens == 0 else ("十" if tens == 1 else _CN_DIGITS[tens] + "十")
    return head + (_CN_DIGITS[ones] if ones else "")


def date_renderings(iso_date: str) -> List[str]:
    """List the ways a date is written in the sources this project reads.

    Args:
        iso_date: A date as ``YYYY-MM-DD``.

    Returns:
        Chinese (in digits and in numerals), US, British and Official
        Journal renderings of the date.

    Raises:
        ValueError: When ``iso_date`` is not a valid ISO date.
    """
    day = datetime.date.fromisoformat(iso_date)
    month = _MONTHS[day.month - 1]
    cn_year = "".join(_CN_DIGITS[int(digit)] for digit in str(day.year))
    return [
        f"{day.year}年{day.month}月{day.day}日",
        f"{day.year}年{day.month:02d}月{day.day:02d}日",
        f"{cn_year}年{_cn_numeral(day.month)}月{_cn_numeral(day.day)}日",
        f"{month} {day.day}, {day.year}",
        f"{day.day} {month} {day.year}",
        f"{day.day}.{day.month}.{day.year}",
        # Publishing systems stamp pages in ISO form, with a leading zero and
        # often a time beside it ("2025-10-09 16:00"). It is still the date the
        # source states, so it counts.
        f"{day.year}-{day.month:02d}-{day.day:02d}",
    ]


def states_token(quote: str, token: str) -> bool:
    """Tell whether ``quote`` contains ``token`` as a whole item.

    Spacing inside the token is flexible, but the match may not touch a
    letter or digit on either side: ``23-52`` is not found in ``23-5233``,
    ``8 July 2026`` is not found in ``18 July 2026``. A Chinese provision
    label is not found where the text names its ``之一`` sibling.

    Args:
        quote: The text to look in.
        token: A date rendering, a case number or a provision label.

    Returns:
        True when the token is present and delimited.
    """
    chars = [char for char in unicodedata.normalize("NFKC", token) if not char.isspace()]
    if not chars:
        return False
    pattern = _NOT_ALNUM_BEFORE + r"\s*".join(re.escape(char) for char in chars) + _NOT_CONTINUED
    return re.search(pattern, unicodedata.normalize("NFKC", quote)) is not None


def quote_states_date(quote: str, iso_date: str) -> bool:
    """Return True when ``quote`` states ``iso_date`` in a known rendering.

    Raises:
        ValueError: When ``iso_date`` is not a valid ISO date.
    """
    return any(states_token(quote, rendering) for rendering in date_renderings(iso_date))


def contains_name(quote: str, name: str, min_chars: int = 1) -> bool:
    """Tell whether ``quote`` contains ``name``, ignoring case and spacing.

    Args:
        quote: The text to look in.
        name: The name of a court or an issuing body.
        min_chars: Shortest name accepted; a fragment such as "法院" names
            nobody in particular.
    """
    wanted = normalize(name).casefold()
    return len(wanted) >= min_chars and wanted in normalize(quote).casefold()


def assess(source_ids: List[str], index: SnapshotIndex) -> Dict[str, str]:
    """Derive the verification level and evidence grade of a record.

    The level is computed from the sources a record rests on, never typed:
    VERIFIED when every source is an official publication, PARSED when at
    least one is a repost, PENDING when the record rests on no snapshot.
    The grade is that of the weakest source kind used.

    Args:
        source_ids: Every snapshot the record quotes. The caller must have
            checked the quotes already.
        index: The snapshot index.

    Returns:
        A mapping with ``verification`` and ``evidence_grade``.
    """
    used = sorted(set(source_ids))
    if not used:
        return {"verification": PENDING, "evidence_grade": "-"}
    entries = [index.entry(source_id) for source_id in used]
    level = VERIFIED if all(entry["official"] for entry in entries) else PARSED
    grade = max(GRADE_BY_KIND[entry["kind"]] for entry in entries)
    return {"verification": level, "evidence_grade": grade}
