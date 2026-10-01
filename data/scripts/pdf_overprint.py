"""Drop the second impression of a glyph a PDF paints twice to fake bold.

Some reports have no true bold face embedded, so their generator simulates one by
painting every glyph of a heading twice, offset by a fraction of a point. The two
impressions blend when the page is read, but they are two separate glyphs in the
content stream, so pdfminer returns both and ``6. ČERPACÍ ZKOUŠKA`` arrives as
``66.. ČČEERRPPAACCÍÍ ZZKKOOUUŠŠKKAA``.

That costs the citation, not just the look of the line. ``_NUMBERED_RE`` in
``markdown_normalizer`` cannot match ``66..`` - two dots, no space after the
number - and the 0.85 similarity fallback does not reach a title whose every
letter is doubled, so the chapter never becomes a heading. Chunks then inherit the
previous heading: four reports lost 10 of 17, 11 of 13, 10 of 17 and 10 of 17
chapters this way, which is 41 of the 52 contents entries the whole corpus fails
to promote.

Deciding by **geometry rather than text** is what makes this safe. Measured over
every adjacent pair of identical characters in one font and size, the second
impression sits at 0.171 of a glyph width or closer, while the nearest legitimate
pair - a real Czech ``nn`` in "denní" - sits at 0.749, a full advance away. The
band between is empty, and three clean reports (Roudno, Pazderna, Myslinka) hold
no pair in it at all. A rule reading the text could never separate the two that
cleanly.

The filter belongs here, in ``render_char``, rather than in a pass over the text
or over the finished layout tree. Characters are suppressed before
``LTPage.analyze`` runs, so word margins, ``LTAnno`` spaces and line grouping are
all computed from true geometry; cleaning up afterwards would mean the heading had
already been assembled out of doubled glyphs. It also means the filter is a no-op
on a report that does not overprint - not one ``LTChar`` differs, so the page text
is unchanged byte for byte, and nothing downstream is invalidated.

Only consecutive copies are handled. A generator that repaints a whole block of
lines puts the copies far apart in the content stream, which this cannot see; no
report in the corpus does that, and the ``pokrytí obsahu`` check in
``check_pipeline`` would report the lost headings if one did.
"""

from __future__ import annotations

import logging

from pdfminer.converter import TextConverter
from pdfminer.layout import LTChar
from pdfminer.pdfpage import PDFPage
from pdfminer.utils import Matrix

logger = logging.getLogger(__name__)

# How far the copy may sit from the original, as a fraction of the glyph's own
# width and height. The fake bold offset measures 0.6pt in each axis: against the
# 3.51pt advance of a 14pt bold period that is 0.171, and against the 14.04pt
# height 0.043 (0.067 on 9pt body text). The nearest same-letter pair that is not
# an overprint is 0.749 of a width away, so anything up to a fifth of a glyph is
# comfortably inside the empty band and still far from a real double letter.
_MAX_OFFSET_WIDTH_RATIO = 0.20
_MAX_OFFSET_HEIGHT_RATIO = 0.12

# Both impressions come from one font at one size, so they agree exactly; the
# tolerance only covers float arithmetic on the text matrix.
_SIZE_TOLERANCE = 0.01


def is_overprint(previous: LTChar, candidate: LTChar) -> bool:
    """Return whether ``candidate`` is a second impression of ``previous``.

    True only when the two are the same character in the same font at the same
    size, and ``candidate`` lies *on top of* ``previous`` instead of after it.
    Whitespace is never judged an overprint: pdfminer derives spaces from gaps
    rather than from glyphs, so a repeated space carries no meaning here.
    """
    text = candidate.get_text()
    if text != previous.get_text() or not text.strip():
        return False
    if candidate.fontname != previous.fontname:
        return False
    if abs(candidate.size - previous.size) > _SIZE_TOLERANCE:
        return False
    if previous.width <= 0 or previous.height <= 0:
        return False
    if abs(candidate.x0 - previous.x0) > previous.width * _MAX_OFFSET_WIDTH_RATIO:
        return False
    return abs(candidate.y0 - previous.y0) <= previous.height * _MAX_OFFSET_HEIGHT_RATIO


class OverprintTextConverter(TextConverter):
    """A ``TextConverter`` that keeps one impression of an overprinted glyph.

    Drop-in replacement for ``TextConverter``: same constructor, same output, one
    glyph per character. ``suppressed`` counts what was dropped, which is what
    proves a document was left untouched - a count of zero means the page text is
    identical to what plain pdfminer would have produced.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.suppressed = 0
        self._previous: LTChar | None = None

    def begin_page(self, page: PDFPage, ctm: Matrix) -> None:
        super().begin_page(page, ctm)
        self._previous = None

    def render_char(self, matrix, font, fontsize, scaling, rise, cid, ncs, graphicstate) -> float:
        """Render one glyph, discarding it when it overprints the one before.

        The advance width is returned whether the glyph was kept or not, because
        the PDF moved the text position either way and the caller adds it to the
        pen. Suppressing the advance too would pull the rest of the line left.
        """
        advance = super().render_char(
            matrix, font, fontsize, scaling, rise, cid, ncs, graphicstate
        )
        item = self.cur_item._objs[-1]
        if self._previous is not None and is_overprint(self._previous, item):
            self.cur_item._objs.pop()
            self.suppressed += 1
            return advance
        self._previous = item
        return advance
