"""Reconstruct document structure in text extracted from a PDF.

A PDF text extractor returns plain text with no font or style information, so it
cannot tell a heading from a paragraph. Reports come out without a single ``#``,
``chunker.py`` falls back to one unnamed section and every chunk loses the
section citation the whole project is built around. This module puts back the
structure the extractor could not see.

Steps run in a fixed order, each depending on the previous one:

1. Unwrap layout tables. Kept for Markdown inputs and as insurance: pdfminer
   produces no pipe tables, but pdfplumber - which this pipeline used to go
   through - rendered multi-column layout as tables, and one of those had
   swallowed a heading.
2. Drop page furniture: running headers and footers repeated across pages.
3. Lift the table of contents out of the body and keep it as the outline.
4. Promote body lines matching that outline to Markdown headings, including
   headings whose section number the extractor detached from their title.
5. Promote the first line to the document title.

Text that is not matched is left alone. ``chunk_raw`` is quoted back to users
and is the full-text index, so this must never rewrite report prose.

Like ``chunker.py`` this makes no API calls and touches no database, so it can
be tuned and tested without credentials.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# Bump when a change here should re-derive Markdown for already-processed
# sources. Mirrors SCHEMA_VERSION in schemas.py; wired into the manifest so the
# markdown -> extract -> chunk -> import cascade re-runs on its own.
MARKDOWN_VERSION = 2

# A pipe block is layout, not data, when most of its cells are empty. Real
# tables in these reports (borehole profiles, laboratory results) are densely
# filled; MarkItDown's fake ones are mostly padding. Measured on the first real
# report: every one of its 46 blocks sat between 11% and 50%.
_TABLE_FILL_THRESHOLD = 0.6

# Running headers and footers repeat across pages. Real prose can repeat a short
# line a few times - one report says "vstupni udaje:" four times in its
# calculations - so the bar scales with the page count instead of being a small
# constant.
_FURNITURE_PAGE_RATIO = 0.5
_FURNITURE_MIN_REPEATS = 3
_FURNITURE_MAX_LENGTH = 80
_FURNITURE_MIN_SIGNATURE = 3

# Guard rails for the no-table-of-contents fallback.
_HEURISTIC_MAX_LENGTH = 90
_HEURISTIC_MIN_HEADINGS = 3

# How far below a heading to look for the section number pdfminer detached from it.
_ORPHAN_SEARCH_LINES = 3

# How close a body line must be to its table-of-contents entry. Not an exact
# match, because pdfminer drops glyphs it cannot map: one report's body reads
# "2. P ehled p irodnich pom r" where its own contents page reads
# "2. Prehled prirodnich pomeru". The section number has to match exactly, so
# this only has to separate a mangled heading from an unrelated numbered line.
_TITLE_SIMILARITY = 0.85

# A document title needs enough substance to be worth a heading; pdfminer
# sometimes leaves a stray glyph as the first line of the document.
_TITLE_MIN_LENGTH = 8
_TITLE_MIN_LETTERS = 4
_TITLE_SEARCH_LINES = 20

# Refuse to lose more than this share of the document's letters and digits.
_MAX_ALNUM_LOSS = 0.25

_TABLE_SEPARATOR_RE = re.compile(r"^\|[\s|:-]*-{2,}[\s|:-]*\|?$")
_TOC_ENTRY_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.+?)\s*\.{4,}\s*(\d+)\s*$")
_NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
_TOC_CAPTION_RE = re.compile(r"^obsah\b", re.IGNORECASE)
_TRAILING_NUMBER_RE = re.compile(r"\s*\d{1,4}$")


@dataclass
class NormalizationStats:
    """What the normaliser changed, for logging and for tuning on new reports."""

    headings: int
    source: str
    tables_unwrapped: int
    furniture_dropped: int
    toc_lines_dropped: int


def fold(text: str) -> str:
    """Return ``text`` normalised for comparison: no accents, no case, one space.

    Headings are printed in capitals in the table of contents and in title case
    in the body, so matching the two needs both folded.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(stripped.split()).casefold()


def _titles_match(body: str, toc: str) -> bool:
    """Return whether a body heading and a contents entry name the same section.

    Compared without spaces: the glyphs pdfminer drops often take the
    surrounding spacing with them.
    """
    left = fold(body).replace(" ", "")
    right = fold(toc).replace(" ", "")
    if left == right:
        return True
    if not left or not right:
        return False
    return SequenceMatcher(None, left, right).ratio() >= _TITLE_SIMILARITY


def _is_table_row(line: str) -> bool:
    """Return whether ``line`` is a Markdown pipe row."""
    stripped = line.strip()
    return len(stripped) > 1 and stripped.startswith("|") and stripped.endswith("|")


def _cells(line: str) -> list[str]:
    """Return the trimmed cells of a pipe row."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _unwrap_tables(lines: list[str]) -> tuple[list[str], int]:
    """Flatten pipe blocks that encode page layout rather than tabular data.

    Blocks are judged as a whole: a sparsely filled block is layout, and each of
    its rows collapses to its non-empty cells joined by a space. Densely filled
    blocks are genuine tables and pass through untouched.
    """
    result: list[str] = []
    unwrapped = 0
    index = 0

    while index < len(lines):
        if not _is_table_row(lines[index]):
            result.append(lines[index])
            index += 1
            continue

        end = index
        while end < len(lines) and _is_table_row(lines[end]):
            end += 1
        block = lines[index:end]
        index = end

        rows = [line for line in block if not _TABLE_SEPARATOR_RE.match(line.strip())]
        cell_count = sum(len(_cells(row)) for row in rows)
        filled = [cell for row in rows for cell in _cells(row) if cell]

        if cell_count and len(filled) / cell_count >= _TABLE_FILL_THRESHOLD:
            result.extend(block)
            continue

        unwrapped += len(rows)
        for row in rows:
            text = " ".join(cell for cell in _cells(row) if cell)
            if text:
                result.append(text)

    return result, unwrapped


def _signature(line: str) -> str | None:
    """Return a comparison key for page-furniture detection, or None.

    The trailing page number is stripped so that "REPORT TITLE 3" and
    "REPORT TITLE 11" collapse onto the same key.
    """
    collapsed = " ".join(line.split())
    if not collapsed or len(collapsed) > _FURNITURE_MAX_LENGTH:
        return None
    key = _TRAILING_NUMBER_RE.sub("", collapsed)
    return key if len(key) >= _FURNITURE_MIN_SIGNATURE else None


def _strip_page_furniture(lines: list[str], page_count: int | None) -> tuple[list[str], int]:
    """Drop short lines that repeat across most pages."""
    threshold = _FURNITURE_MIN_REPEATS
    if page_count:
        threshold = max(threshold, round(page_count * _FURNITURE_PAGE_RATIO))

    counts: Counter[str] = Counter()
    for line in lines:
        signature = _signature(line)
        if signature:
            counts[signature] += 1

    furniture = {key for key, count in counts.items() if count >= threshold}
    if not furniture:
        return lines, 0

    kept = [line for line in lines if _signature(line) not in furniture]
    return kept, len(lines) - len(kept)


def _extract_toc(lines: list[str]) -> tuple[list[str], dict[str, str], int]:
    """Pull the table of contents out of the body.

    Returns the remaining lines, the outline as ``{number: title}``, and how
    many lines the table of contents occupied. The entries are dropped from the
    body: they are navigation, and their dot leaders are noise inside a chunk.
    """
    matches = [index for index, line in enumerate(lines) if _TOC_ENTRY_RE.match(line.strip())]
    if len(matches) < _HEURISTIC_MIN_HEADINGS:
        return lines, {}, 0

    start, end = matches[0], matches[-1]
    outline: dict[str, str] = {}
    for index in matches:
        match = _TOC_ENTRY_RE.match(lines[index].strip())
        if match is not None:
            outline.setdefault(match.group(1), match.group(2))

    # Swallow the "Obsah" caption sitting immediately above the first entry.
    while start > 0 and not lines[start - 1].strip():
        start -= 1
    if start > 0 and _TOC_CAPTION_RE.match(lines[start - 1].strip()):
        start -= 1

    remaining = lines[:start] + lines[end + 1 :]
    return remaining, outline, end + 1 - start


def _number_tuple(number: str) -> tuple[int, ...]:
    """Return a dotted section number as a tuple of integers."""
    return tuple(int(part) for part in number.split("."))


def _follows(previous: tuple[int, ...] | None, current: tuple[int, ...]) -> bool:
    """Return whether ``current`` can directly follow ``previous`` in an outline."""
    if previous is None:
        return current == (1,)
    if len(current) == len(previous) + 1 and current[:-1] == previous and current[-1] == 1:
        return True
    if len(current) <= len(previous):
        head = current[:-1]
        return head == previous[: len(head)] and current[-1] == previous[len(head)] + 1
    return False


def _heading_prefix(number: str, line: str) -> str:
    """Return ``line`` prefixed with hashes for the depth of its section number."""
    depth = min(number.count(".") + 2, 6)
    return f"{'#' * depth} {' '.join(line.split())}"


def _heuristic_headings(lines: list[str]) -> set[int]:
    """Find numbered headings in a report that has no table of contents.

    Annex and distribution lists look exactly like headings, which is what makes
    a naive rule fail, so a candidate only counts as part of an outline that
    starts at 1 and stays continuous. The longest such chain wins - an annex list
    restarts the numbering and therefore yields a shorter one.
    """
    candidates: list[tuple[int, tuple[int, ...]]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if len(stripped) > _HEURISTIC_MAX_LENGTH:
            continue
        match = _NUMBERED_RE.match(stripped)
        if not match:
            continue
        title = match.group(2).strip()
        if len(title) < 3 or title[-1] in ".,;:":
            continue
        number = _number_tuple(match.group(1))
        if len(number) > 3:
            continue
        candidates.append((index, number))

    best: list[int] = []
    for start in range(len(candidates)):
        if candidates[start][1] != (1,):
            continue
        chain = [candidates[start][0]]
        previous = candidates[start][1]
        for index, number in candidates[start + 1 :]:
            if _follows(previous, number):
                chain.append(index)
                previous = number
        if len(chain) > len(best):
            best = chain

    return set(best) if len(best) >= _HEURISTIC_MIN_HEADINGS else set()


def _letters(text: str) -> int:
    """Count alphabetic characters."""
    return sum(1 for char in text if char.isalpha())


def _apply_outline(lines: list[str], outline: dict[str, str]) -> tuple[list[str], int]:
    """Prefix body lines that match the outline with the right number of hashes.

    The body wording wins, because a contents page is usually set in capitals and
    the body is not. The exception is a body heading that lost glyphs the
    contents page kept - there the contents wording is the same heading, only
    intact, and the section label is what gets cited back to users.
    """
    applied = 0
    result = list(lines)
    placed: dict[str, int] = {}

    for index, line in enumerate(result):
        match = _NUMBERED_RE.match(line.strip())
        if not match:
            continue
        number, title = match.group(1), match.group(2)
        expected = outline.get(number)
        if expected is None or number in placed or not _titles_match(title, expected):
            continue
        if _letters(expected) > _letters(title):
            line = f"{number}. {expected}"
        result[index] = _heading_prefix(number, line)
        placed[number] = index
        applied += 1

    return result, applied + _apply_detached(result, outline, placed)


def _is_isolated(lines: list[str], index: int) -> bool:
    """Return whether a line stands alone between blank lines."""
    before = lines[index - 1].strip() if index > 0 else ""
    after = lines[index + 1].strip() if index + 1 < len(lines) else ""
    return not before and not after


def _apply_detached(lines: list[str], outline: dict[str, str], placed: dict[str, int]) -> int:
    """Promote headings whose section number got separated from their title.

    pdfminer emits some headings as the bare title on one line and the number on
    another, so the numbered pass never sees them. The title alone is enough here
    because the contents page supplies the number - but only within the span the
    neighbouring already-placed headings leave free, so a phrase that recurs in
    the prose cannot claim a heading. A one-word title additionally has to stand
    alone between blank lines; "Uvod" is too common to promote on sight.
    """
    numbers = list(outline)
    applied = 0

    for position, number in enumerate(numbers):
        if number in placed:
            continue
        title = outline[number]
        low = max((placed[n] for n in numbers[:position] if n in placed), default=-1)
        high = min((placed[n] for n in numbers[position + 1 :] if n in placed), default=len(lines))

        for index in range(low + 1, high):
            stripped = lines[index].strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not _titles_match(stripped, title):
                continue
            if len(title.split()) < 2 and not _is_isolated(lines, index):
                continue
            lines[index] = _heading_prefix(number, f"{number}. {stripped}")
            _drop_orphan_number(lines, index, number)
            placed[number] = index
            applied += 1
            break

    return applied


def _drop_orphan_number(lines: list[str], index: int, number: str) -> None:
    """Blank the section number left stranded near a heading it belongs to.

    Deliberately narrow: only a line that is exactly this heading's number, only
    just below it. Bare numbers elsewhere in these reports are years and measured
    values, so nothing broader is safe.
    """
    for probe in range(index + 1, min(index + _ORPHAN_SEARCH_LINES + 1, len(lines))):
        if lines[probe].strip() in {number, f"{number}."}:
            lines[probe] = ""
            return


def _apply_heuristic(lines: list[str], indexes: set[int]) -> list[str]:
    """Prefix the heuristically found heading lines with hashes."""
    result = list(lines)
    for index in indexes:
        match = _NUMBERED_RE.match(result[index].strip())
        if match is not None:
            result[index] = _heading_prefix(match.group(1), result[index])
    return result


def _promote_title(lines: list[str]) -> tuple[list[str], bool]:
    """Turn the report's opening line into the top-level heading.

    Gives the cover page and anything else ahead of the first numbered section a
    citation instead of no section at all. The first line is not always usable:
    the running header is by then already gone as page furniture, and pdfminer
    can leave a stray glyph in its place, so the first line with real words wins
    and is hoisted to the top - anything above it would otherwise keep forming a
    leading section with no name.
    """
    result = list(lines)
    seen = 0
    for index, line in enumerate(result):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return result, False
        seen += 1
        if seen > _TITLE_SEARCH_LINES:
            return result, False
        if len(stripped) >= _TITLE_MIN_LENGTH and _letters(stripped) >= _TITLE_MIN_LETTERS:
            heading = f"# {' '.join(stripped.split())}"
            del result[index]
            return [heading, ""] + result, True
    return result, False


def _collapse_blank_lines(lines: list[str]) -> list[str]:
    """Reduce runs of three or more blank lines to two."""
    result: list[str] = []
    blanks = 0
    for line in lines:
        if line.strip():
            blanks = 0
            result.append(line)
            continue
        blanks += 1
        if blanks <= 2:
            result.append("")
    return result


def _alnum_count(text: str) -> int:
    """Count letters and digits, ignoring the punctuation this module removes."""
    return sum(1 for char in text if char.isalnum())


def normalize_markdown(raw: str, page_count: int | None = None) -> tuple[str, NormalizationStats]:
    """Rebuild headings and strip extraction artefacts in raw page text.

    Args:
        raw: Text exactly as the PDF extractor produced it, pages joined.
        page_count: Source page count, used to scale the page-furniture
            threshold. Omit it and a fixed minimum applies.

    Returns:
        The normalised Markdown and what was changed. On a suspiciously large
        loss of text the original is returned unchanged with empty stats.
    """
    lines = raw.splitlines()

    lines, tables_unwrapped = _unwrap_tables(lines)
    lines, furniture_dropped = _strip_page_furniture(lines, page_count)
    lines, outline, toc_lines_dropped = _extract_toc(lines)

    if outline:
        lines, headings = _apply_outline(lines, outline)
        source = "toc" if headings else "none"
        if not headings:
            logger.warning("Table of contents found but no heading matched the body")
    else:
        indexes = _heuristic_headings(lines)
        lines = _apply_heuristic(lines, indexes)
        headings = len(indexes)
        source = "heuristic" if headings else "none"

    if headings:
        lines, titled = _promote_title(lines)
        headings += int(titled)

    normalised = "\n".join(_collapse_blank_lines(lines)).strip() + "\n"

    original_alnum = _alnum_count(raw)
    if original_alnum:
        lost = 1 - _alnum_count(normalised) / original_alnum
        if lost > _MAX_ALNUM_LOSS:
            logger.warning(
                "Normalisation would drop %.0f%% of the text; keeping the raw conversion",
                lost * 100,
            )
            return raw, NormalizationStats(0, "none", 0, 0, 0)

    if source == "none":
        logger.warning("No headings recovered; chunks will have no section citation")

    return normalised, NormalizationStats(
        headings=headings,
        source=source,
        tables_unwrapped=tables_unwrapped,
        furniture_dropped=furniture_dropped,
        toc_lines_dropped=toc_lines_dropped,
    )
