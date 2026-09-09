"""Tests for the prose/form page classifier.

The fixtures reproduce the *shape* of the four page kinds in the corpus - line
lengths and word composition - without carrying report content: localities,
companies and people are left out, since the source documents are internal.
"""

from __future__ import annotations

from page_classifier import EMPTY, FORM, PROSE, classify_pages, page_features

# Report body: every line runs to the margin, ordinary Czech throughout.
PROSE_PAGE = """Projektovaná hala má nepravidelný půdorys o rozměru 72,8 - 120,8 x 72,8 - 84,8 m a
nachází se v jihovýchodní okrajové části území. Podlaha haly je situována ve výškové
úrovni 384,40 m n. m. Terén v místě půdorysu je mírně ukloněný k východu až jihovýchodu
v intervalu nadmořských výšek cca 381,2 až 385,2 m n.m. Ornice se v daném prostoru
nenachází, terén byl v minulosti dosypán navážkami o mocnosti do 1,5 m.
"""

# Borehole log: depth intervals and lithology. Reads like a table and has fewer
# function words than the form sheet below, but the descriptions are clauses.
BOREHOLE_LOG_PAGE = """Pokračování popisu vrtu J1
9,00 – 9,80 :
Prachovec, velmi zvětralý, hnědožlutý, charakteru středně
plastického jílu pevné konzistence, slabě slídnatý, na
vrstevních plochách limonitizovaný - karbon, slánské souvrství
R6/F6 GT7
9,80 – 11,60 :
Pískovec, s proplástky prachovce, mírně zvětralý, jemně až
středně zrnitý, šedý a okrově žlutý, kusovitě rozpadavý
"""

# Laboratory form: a caption in whole words, then one cell per line. The caption
# is what makes this page richer in function words than the borehole log above.
FORM_PAGE = """STANOVENÍ ZHUTNITELNOSTI
PROCTOR STANDARD
Pro hutnění při různých vlhkostech bylo použito téhož vzorku
Akce:
Sonda :
Přirozená vlhkost :
Zdánlivá hustota zeminy:
Obsah frakce pod 5 mm:
Typ zeminy:
J 2
7,5 %
2722 kg/m3
100 %
PÍSČITÁ HLÍNA
Lab. číslo:
Hloubky:
692
1,1 - 1,4 m
"""

# Rotated scanned table: pdfminer reads the glyphs, one per line, and there is
# nothing left to retrieve.
GLYPH_SOUP_PAGE = """«
«
a
k
m
E
á
c
n
z
o
O
P
Q.
X■u -
2 m
0
,
4 (N
"""


def _kind(page: str) -> str:
    """Classify one page on its own, without run smoothing."""
    return classify_pages([page])[0]


def test_report_body_is_prose():
    assert _kind(PROSE_PAGE) == PROSE


def test_form_sheet_is_a_form():
    assert _kind(FORM_PAGE) == FORM


def test_rotated_scanned_table_is_a_form():
    assert _kind(GLYPH_SOUP_PAGE) == FORM


def test_page_without_text_is_empty():
    assert _kind("   \n\n \x0c") == EMPTY


def test_borehole_log_is_kept_as_prose():
    """The single most retrieval-valuable page shape in the corpus.

    Its stopword share is lower than the form sheet's, so a rule on function
    words alone would discard the lithology descriptions users actually search
    for. Only the conjunction with the long-line share keeps it.
    """
    log_long, log_stop = page_features(BOREHOLE_LOG_PAGE)
    form_long, form_stop = page_features(FORM_PAGE)

    assert log_stop < form_stop, "the borehole log really is the poorer in function words"
    assert log_long > form_long, "and the long-line share is what has to save it"
    assert _kind(BOREHOLE_LOG_PAGE) == PROSE


def test_a_single_table_inside_a_chapter_does_not_split_it():
    """One form page between prose pages is part of the chapter around it."""
    pages = [PROSE_PAGE, PROSE_PAGE, FORM_PAGE, PROSE_PAGE, PROSE_PAGE]
    assert classify_pages(pages) == [PROSE] * 5


def test_a_sustained_run_of_forms_survives_smoothing():
    """An annex is long, so smoothing must leave it alone."""
    pages = [PROSE_PAGE, PROSE_PAGE] + [FORM_PAGE] * 4
    assert classify_pages(pages) == [PROSE, PROSE] + [FORM] * 4


def test_blank_pages_do_not_split_an_annex():
    """Scanned annex pages carry no text; the annex around them is contiguous."""
    pages = [PROSE_PAGE] + [FORM_PAGE] * 2 + ["  \n"] * 3 + [FORM_PAGE] * 2
    kinds = classify_pages(pages)
    assert kinds[0] == PROSE
    assert [kind for kind in kinds[1:] if kind != EMPTY] == [FORM] * 4
