"""Tell a page of prose from a page of filled-in form.

Geological reports carry their borehole logs, laboratory certificates and
coordinate tables after the report body, and those pages have no headings. The
pipeline had no notion of them, which broke three things at once:

- the page-furniture threshold scales with the page count, but the repeats come
  from the annex, so the same annex deletes 12278 lines from a 265-page report
  and nothing at all from a 130-page one;
- the 25% text-loss guard then fires on the first of those and throws away the
  whole normalisation, headings included;
- and with no heading of its own, the annex inherits the last chapter's label,
  so 130 of 216 chunks in one report are cited as "8.4. Závěrečné zhodnocení".

Two measurements per page separate them, both free and offline:

``long line share``
    Prose wraps at the right margin, so most of its lines are long. A form cell
    holds two words.

``stopword share``
    A Czech sentence cannot be written without ``je``, ``na``, ``se``, ``pro``.
    A table has none.

A page is a form only when **both** are low, and the conjunction is what makes
the rule safe. Borehole logs are the most valuable text in this corpus and read
almost like a table - one measured at 1% stopwords, lower than any real form -
but their lithology descriptions are full sentences, so the long-line share
keeps them. Conversely a Proctor test sheet scored 10% stopwords, higher than
that borehole log, on the strength of one caption; its short lines give it away.
Neither measurement works alone.

The thresholds come from the 15 reports converted so far, where they separate
0.0-8.8% form characters in the ten healthy reports from 28.5-79.5% in the five
broken ones. They are tuned to a corpus, not universal, so expect to revisit
them when reports from another surveyor arrive.
"""

from __future__ import annotations

import re
import unicodedata

PROSE = "prose"
FORM = "form"
EMPTY = "empty"

# A line at least this long was wrapped by the margin rather than by a cell.
_LONG_LINE_CHARS = 45

# Shares below which a page stops looking like prose. Both must be under.
_LONG_LINE_SHARE = 0.12
_STOPWORD_SHARE = 0.06

# A single page never flips the classification on its own: one table inside a
# chapter is part of that chapter, and one prose page inside the annex is a
# divider. A run has to be at least this long to stand.
_MIN_RUN_PAGES = 2

# Two letters minimum. Czech's single-letter prepositions (a, i, v, k, s, z, o,
# u) are exactly the characters that rotated scanned tables decompose into -
# "« | a | k | m | E | á | c | n | z | o" - so counting them would raise the
# stopword share of the very pages this is meant to catch.
_TOKEN_RE = re.compile(r"[^\W\d_]{2,}", re.UNICODE)

# Verbs, conjunctions, pronouns and adverbs - deliberately no prepositions.
# A form uses "od", "do", "po", "na" in its field labels as freely as prose does:
# "od - do:" alone put the 93 borehole-log pages of one report at 6-7%, over the
# threshold, and they stayed in the body. Without prepositions the same pages
# measure 0.0-0.6%, because what a form never contains is a verb.
_STOPWORDS = frozenset(
    """
    se si je jsou jsem jsme jste byl byla bylo byly byt ma maji lze bude budou
    muze ze kdy kde ktery ktera ktere kterou kterym kterych nebo ale tak jako
    vsak take jen jeste jiz coz tedy dle podle proto tim pouze zejmena tzv resp
    """.split()
)


def _fold(text: str) -> str:
    """Return ``text`` lowercased with diacritics removed."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def page_features(page: str) -> tuple[float, float] | None:
    """Return ``(long line share, stopword share)`` for one page, or None.

    None means the page carries no text at all - a scan without an OCR layer, or
    a separator.
    """
    lines = [line.strip() for line in page.splitlines() if line.strip()]
    if not lines:
        return None

    long_lines = sum(1 for line in lines if len(line) >= _LONG_LINE_CHARS)
    tokens = _TOKEN_RE.findall(_fold(page))
    stopwords = sum(1 for token in tokens if token in _STOPWORDS)

    return (
        long_lines / len(lines),
        stopwords / len(tokens) if tokens else 0.0,
    )


def _classify_one(page: str) -> str:
    """Classify a single page, before run smoothing."""
    features = page_features(page)
    if features is None:
        return EMPTY
    long_share, stopword_share = features
    if long_share < _LONG_LINE_SHARE and stopword_share < _STOPWORD_SHARE:
        return FORM
    return PROSE


def _smooth(kinds: list[str]) -> list[str]:
    """Absorb runs shorter than ``_MIN_RUN_PAGES`` into their surroundings.

    Empty pages are transparent: a scanned page in the middle of the annex must
    not split it into two runs, since the whole point is to keep the annex
    contiguous.
    """
    positions = [index for index, kind in enumerate(kinds) if kind != EMPTY]
    if not positions:
        return list(kinds)

    smoothed = list(kinds)
    runs: list[list[int]] = []
    for index in positions:
        if runs and smoothed[runs[-1][-1]] == smoothed[index]:
            runs[-1].append(index)
        else:
            runs.append([index])

    for order, run in enumerate(runs):
        if len(run) >= _MIN_RUN_PAGES or order == 0 or order == len(runs) - 1:
            continue
        before = smoothed[runs[order - 1][-1]]
        after = smoothed[runs[order + 1][0]]
        if before == after:
            for index in run:
                smoothed[index] = before
    return smoothed


def classify_pages(pages: list[str]) -> list[str]:
    """Classify every page as ``prose``, ``form`` or ``empty``.

    The result is positional: element *i* describes ``pages[i]``.
    """
    return _smooth([_classify_one(page) for page in pages])
