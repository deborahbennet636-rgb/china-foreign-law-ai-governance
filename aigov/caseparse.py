"""Cut one case out of a court digest page.

Courts publish "typical cases" as one long page: a numbered block per case,
and inside each block a few fixed headings (facts, result, significance).
The functions here locate a block and copy its sections out paragraph by
paragraph, so that case excerpts are extracted from the snapshot rather
than typed by hand.
"""
from typing import Dict, List, Mapping, Sequence, Tuple


def clean_lines(text: str) -> List[str]:
    """Return the non-empty lines of ``text`` with surrounding space removed."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def extract_block(lines: Sequence[str], start: str, end: str) -> List[str]:
    """Return the lines of one case block.

    The block begins at the last line that starts with ``start``. Digest
    pages often list every case title in a table of contents first, and
    the last occurrence is the one in the body. The block stops before the
    first later line that starts with ``end``.

    Args:
        lines: Cleaned lines of the page.
        start: Prefix of the first line of the block.
        end: Prefix of the first line after the block.

    Returns:
        The lines of the block, including its first line.

    Raises:
        ValueError: When either marker is missing.
    """
    starts = [index for index, line in enumerate(lines) if line.startswith(start)]
    if not starts:
        raise ValueError(f"block start {start!r} not found")
    begin = starts[-1]
    for stop in range(begin + 1, len(lines)):
        if lines[stop].startswith(end):
            return list(lines[begin:stop])
    raise ValueError(f"block end {end!r} not found after {start!r}")


def split_sections(
    block: Sequence[str],
    sections: Mapping[str, str],
    stop: Sequence[str] = (),
) -> Tuple[List[str], Dict[str, List[str]]]:
    """Split a case block into its title lines and named sections.

    Args:
        block: Lines of one case block.
        sections: Excerpt kind mapped to the heading line that opens it.
        stop: Heading lines that close a section without opening one, such
            as a trailing case-number heading.

    Returns:
        The title lines before the first heading, and the paragraphs of
        each section keyed by excerpt kind.

    Raises:
        ValueError: When a heading is missing, repeated, or has no text.
    """
    kind_of = {heading: kind for kind, heading in sections.items()}
    title: List[str] = []
    found: Dict[str, List[str]] = {}
    current: List[str] = title
    for line in block:
        if line in kind_of:
            kind = kind_of[line]
            if kind in found:
                raise ValueError(f"heading {line!r} appears twice in one block")
            found[kind] = []
            current = found[kind]
        elif line in stop:
            current = []
        else:
            current.append(line)
    for kind, heading in sections.items():
        if not found.get(kind):
            raise ValueError(f"section {heading!r} is missing or empty")
    return title, found
