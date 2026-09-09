"""Tests for the section-aware chunker.

``chunker.py`` is a pure function with no API calls and no database, so this
suite runs without credentials and without Docker.

Four of these tests describe defects measured on the real corpus rather than
behaviour the module has today. They are the acceptance criteria for the
chunker fixes; each names the measurement that motivated it.
"""

from __future__ import annotations

import pytest

from chunker import chunk_markdown, count_tokens


def _paragraph(target_tokens: int, word: str = "zemina") -> str:
    """Return a paragraph of at least ``target_tokens`` tokens."""
    words: list[str] = []
    while count_tokens(" ".join(words)) < target_tokens:
        words.append(word)
    return " ".join(words)


def _distinct_paragraphs(count: int, target_tokens: int) -> list[str]:
    """Return ``count`` paragraphs no two of which share any wording.

    Repeating one paragraph would make every window look like it overlaps its
    neighbour, because the boundary text matches by coincidence.
    """
    return [f"sonda-{index}: {_paragraph(target_tokens, f'vrstva{index}')}" for index in range(count)]


def _longest_common_boundary(first: str, second: str) -> int:
    """Return how many characters of ``first``'s tail open ``second``."""
    for size in range(min(len(first), len(second)), 0, -1):
        if first[-size:] == second[:size]:
            return size
    return 0


# --------------------------------------------------------------------------- #
# Behaviour that is correct today and must not regress
# --------------------------------------------------------------------------- #


def test_heading_path_becomes_the_section_label():
    """The full heading path is the citation unit, joined with ' > '."""
    markdown = (
        "# Posudek\n\n"
        "## 3. Geologické poměry\n\n"
        "Kvartérní pokryv je tvořen sprašovými hlínami.\n\n"
        "### 3.2. Podzemní vody\n\n"
        "Hladina byla naražena v hloubce 3,2 m.\n"
    )
    sections = {chunk.section for chunk in chunk_markdown(markdown, min_tokens=1)}
    assert "Posudek > 3. Geologické poměry" in sections
    assert "Posudek > 3. Geologické poměry > 3.2. Podzemní vody" in sections


def test_document_without_headings_becomes_one_unnamed_section():
    """A heading-less document still chunks, with no section citation."""
    chunks = chunk_markdown(_paragraph(50), min_tokens=1)
    assert chunks
    assert all(chunk.section is None for chunk in chunks)


def test_overlap_must_be_smaller_than_max_tokens():
    """A window that cannot advance is a configuration error, not a hang."""
    with pytest.raises(ValueError):
        chunk_markdown("text", max_tokens=100, overlap=100)


# --------------------------------------------------------------------------- #
# Defects measured on the corpus. These are the acceptance criteria.
# --------------------------------------------------------------------------- #


def test_chunks_never_exceed_max_tokens():
    """Windowing sums per-paragraph counts, then joins with separators.

    The separators are never counted, so the result overshoots: 73 of 216 chunks
    in ``IG a HG pruzkum Myslinka 2018`` exceed the nominal 800, the largest at
    941. Sixty short paragraphs reproduce it deterministically.
    """
    body = "## Sekce A\n\n" + "\n\n".join([_paragraph(8)] * 60)
    chunks = chunk_markdown(body, max_tokens=200, overlap=20, min_tokens=1)
    oversized = [chunk.token_count for chunk in chunks if chunk.token_count > 200]
    assert not oversized, f"chunks over max_tokens: {oversized}"


def test_consecutive_windows_of_a_section_overlap():
    """Overlap is carried whole paragraphs at a time, or not at all.

    ``_window_tokens`` breaks out of the carry loop as soon as one paragraph
    would exceed the overlap budget, so a section whose paragraphs are larger
    than ``overlap`` gets none. Measured on the corpus: 27% of consecutive
    same-section pairs share zero characters.
    """
    body = "## Sekce A\n\n" + "\n\n".join(_distinct_paragraphs(6, 70))
    chunks = chunk_markdown(body, max_tokens=200, overlap=50, min_tokens=1)
    assert len(chunks) > 1

    without_overlap = [
        index
        for index in range(len(chunks) - 1)
        if _longest_common_boundary(chunks[index].text, chunks[index + 1].text) == 0
    ]
    assert not without_overlap, f"window pairs with no overlap: {without_overlap}"


def test_every_window_carries_its_heading():
    """The heading is prefixed to the body, then the body is windowed.

    Only the first window therefore contains the section title. ``fts_chunk`` is
    built from ``chunk_raw``, so a keyword search for the section name cannot
    find any continuation of a long section.
    """
    body = "## Hydrogeologické poměry\n\n" + "\n\n".join(_distinct_paragraphs(6, 70))
    chunks = chunk_markdown(body, max_tokens=200, overlap=50, min_tokens=1)
    assert len(chunks) > 1

    missing = [
        index
        for index, chunk in enumerate(chunks)
        if "Hydrogeologické poměry" not in chunk.text
    ]
    assert not missing, f"windows without their heading: {missing}"


def test_merging_never_moves_text_under_another_sections_label():
    """``_merge_small`` merges forward and keeps the *previous* label.

    An undersized section is glued onto the preceding piece and loses its own
    heading path, so its text is cited as belonging to the section above it.
    """
    markdown = (
        "## Sekce A\n\n"
        + _paragraph(40)
        + "\n\n## Sekce B\n\n"
        + _paragraph(40)
        + "\n"
    )
    for chunk in chunk_markdown(markdown, max_tokens=800, overlap=100, min_tokens=150):
        if chunk.section == "Sekce A":
            assert "Sekce B" not in chunk.text, "text of Sekce B cited as Sekce A"
