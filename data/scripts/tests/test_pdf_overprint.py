"""Tests for telling a faked bold glyph apart from a real double letter.

Both sides cost something. A missed overprint costs the chapter its heading, and
with it the citation of every chunk under it. A false positive is worse and
quieter: it would eat a letter out of the prose that gets embedded and searched,
and nothing downstream would report it. The coordinates here are the ones
pdfminer reports for page 11 of GF_P185441, where "6. ČERPACÍ ZKOUŠKA" is painted
twice.
"""

from __future__ import annotations

from dataclasses import dataclass

from pdf_overprint import is_overprint


@dataclass(frozen=True)
class _Char:
    """Just enough of an LTChar for the predicate: text, box, font and size."""

    text: str
    x0: float
    y0: float
    width: float = 7.02
    height: float = 14.04
    fontname: str = "SOBEVW+TimesNewRoman,Bold"
    size: float = 14.04

    def get_text(self) -> str:
        return self.text


def test_the_second_impression_of_a_faked_bold_glyph_is_found():
    """The case the module exists for: '6' painted at 71.40 and again at 70.80."""
    first = _Char("6", x0=71.40, y0=754.41)
    second = _Char("6", x0=70.80, y0=755.01)

    assert is_overprint(first, second)


def test_the_narrowest_glyph_is_still_recognised():
    """A period is 3.51pt wide, so 0.6pt of offset is 0.171 of it - the tight case."""
    first = _Char(".", x0=78.48, y0=754.41, width=3.51)
    second = _Char(".", x0=77.88, y0=755.01, width=3.51)

    assert is_overprint(first, second)


def test_a_third_impression_is_measured_against_the_one_that_was_kept():
    """What lets three copies collapse to one rather than to two."""
    kept = _Char("6", x0=71.40, y0=754.41)
    third = _Char("6", x0=70.20, y0=755.61)

    assert is_overprint(kept, third)


def test_a_real_czech_double_letter_survives():
    """The "nn" of "denní" sits a full advance apart, not on top of itself."""
    first = _Char("n", x0=120.00, y0=600.00)
    second = _Char("n", x0=127.02, y0=600.00)

    assert not is_overprint(first, second)


def test_the_same_letter_on_the_next_line_survives():
    """Identical x, a line further down - which is why the height is checked too."""
    first = _Char("v", x0=70.00, y0=600.00)
    second = _Char("v", x0=70.00, y0=586.00)

    assert not is_overprint(first, second)


def test_a_different_font_at_the_same_place_survives():
    """Two fonts over one spot is a stamp or a watermark, not a doubled glyph."""
    first = _Char("A", x0=70.00, y0=600.00)
    second = _Char("A", x0=70.20, y0=600.10, fontname="Arial")

    assert not is_overprint(first, second)


def test_a_different_size_at_the_same_place_survives():
    first = _Char("A", x0=70.00, y0=600.00)
    second = _Char("A", x0=70.20, y0=600.10, size=9.0)

    assert not is_overprint(first, second)


def test_a_repeated_space_is_never_an_overprint():
    """pdfminer derives spaces from gaps, so collapsing them would move words."""
    first = _Char(" ", x0=70.00, y0=600.00)
    second = _Char(" ", x0=70.10, y0=600.00)

    assert not is_overprint(first, second)


def test_a_glyph_without_a_box_is_never_an_overprint():
    """A zero width would make every offset infinitely small."""
    first = _Char("A", x0=70.00, y0=600.00, width=0.0)
    second = _Char("A", x0=70.00, y0=600.00)

    assert not is_overprint(first, second)
