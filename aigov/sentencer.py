"""Deterministic multilingual sentence splitter for legal excerpts.

Designed for Chinese, English and German judgments, regulatory orders and
official case digests. Every split preserves all non-whitespace characters in
their original order so that downstream provenance checks can verify
sequential verbatim reconstruction.
"""
import re
from typing import List

_CJK_CLOSERS = "”’」』》）】)]"
_CJK_CONT_AFTER_QUOTE = "，、；：的之等并"
_WESTERN_CLOSERS = "\"'”’)]"

# Dotted legal and general abbreviations that do not end a sentence.
_ABBREV_RE = re.compile(
    r"(?:^|[\s(\[‘“\"'])(?:"
    r"v|vs|no|nos|inc|co|ltd|corp|llc|e\.v|u\.s\.c|c\.f\.r|art|arts|sec|secs|"
    r"abs|s|sog|az|nr|dr|mr|mrs|ms|prof|st|al|et\s+al|i\.e|e\.g|p|pp|n|"
    r"cir|d\.c|dist|ct|fed|supp|app|bzw|z\.b|vgl|u\.a"
    r")\.$",
    re.IGNORECASE,
)

# German/list ordinals such as "Der 5. Zivilsenat" or "1. Item", excluding
# sentence-final references like "Article 5." or "Section 3.".
_GERMAN_ORDINAL_RE = re.compile(
    r"(?:^|\b(?:der|dem|des|die|das|im|am|vom|zum|zur|nach|seit|bis)\s+)\d{1,2}\.$",
    re.IGNORECASE,
)


def _ends_with_protected_dot(chunk: str) -> bool:
    """Return True when a trailing '.' belongs to a dotted abbreviation or German ordinal."""
    stripped = chunk.rstrip()
    if not stripped.endswith("."):
        return False
    if stripped.endswith(".."):
        return True
    if _ABBREV_RE.search(stripped):
        return True
    if _GERMAN_ORDINAL_RE.search(stripped):
        return True
    return False


def _split_paragraph(paragraph: str) -> List[str]:
    """Split a single paragraph without newlines into sentences."""
    text = paragraph.strip()
    if not text:
        return []

    sentences: List[str] = []
    start = 0
    length = len(text)
    index = 0

    while index < length:
        char = text[index]

        if char in "。！？":
            end = index + 1
            had_closer = False
            while end < length and text[end] in _CJK_CLOSERS:
                had_closer = True
                end += 1
            if had_closer and end < length and text[end] in _CJK_CONT_AFTER_QUOTE:
                index = end
                continue
            piece = text[start:end].strip()
            if piece:
                sentences.append(piece)
            start = end
            index = end
            continue

        if char in ".!?":
            # Skip ellipses ("...") and decimal/date/section dots ("5.1", "10.12.2025", "310 O.22723").
            if char == "." and index + 1 < length and not text[index + 1].isspace() and text[index + 1] not in _WESTERN_CLOSERS:
                index += 1
                continue

            end = index + 1
            while end < length and text[end] in _WESTERN_CLOSERS:
                end += 1

            at_boundary = end >= length or text[end].isspace()
            candidate = text[start:end]
            if at_boundary and (char != "." or not _ends_with_protected_dot(text[start : index + 1])):
                piece = candidate.strip()
                if piece:
                    sentences.append(piece)
                start = end
                index = end
                continue

        index += 1

    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def split_sentences(text: str) -> List[str]:
    """Split a legal excerpt into sentences across paragraph breaks.

    Args:
        text: Excerpt text from a validated case record.

    Returns:
        Non-empty sentence strings in exact source order.
    """
    sentences: List[str] = []
    for paragraph in text.splitlines():
        sentences.extend(_split_paragraph(paragraph))
    return sentences
