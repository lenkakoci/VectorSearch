"""Tests for telling a table apart from a page that merely looks like one.

The point of the detector is a number someone will spend money on, so the
failure that matters is a false positive: every indented paragraph counted as a
borehole table turns the measurement into noise. These tests fix both sides -
the grid on Myslinka page 5 is found, and the things that resemble it are not.
"""

from __future__ import annotations

import table_detect
from table_detect import Cell, find_tables, group_rows


def _row(y: float, positions: list[tuple[float, str]]) -> list[Cell]:
    return [Cell(x0=x, x1=x + 30, y0=y, text=text) for x, text in positions]


# The header and the first data rows of "Tabulka 1. Přehled provedených sond",
# at the coordinates pdfminer reports for them.
MYSLINKA = [
    *_row(562.8, [(95.6, "Sonda"), (129.4, "Hloubka"), (178.1, "vzorek pro"),
                  (240.7, "porušený"), (308.8, "Vzorek")]),
    *_row(521.6, [(104.4, "J1"), (137.0, "12,0"), (178.9, "1,1-1,4 m"),
                  (240.7, "1,1-1,4 m"), (304.0, "5,0-9,0 m")]),
    *_row(511.3, [(104.4, "J2"), (137.0, "12,0"), (178.9, "1,1-1,4 m"),
                  (240.7, "2,0-2,5 m"), (304.0, "4,0-7,0 m")]),
    *_row(501.0, [(101.2, "J10"), (137.0, "20,0"), (174.3, "19,23-19,38"),
                  (240.7, "0,5-2,5 m"), (304.0, "0,5-4,0 m")]),
]


def test_a_borehole_table_is_found_with_its_shape_and_header():
    """The case the whole module exists for."""
    tables = find_tables(MYSLINKA)

    assert len(tables) == 1
    table = tables[0]
    assert table.shape == (4, 5)
    assert table.header == ["Sonda", "Hloubka", "vzorek pro", "porušený", "Vzorek"]


def test_a_column_survives_cells_that_start_a_little_differently():
    """J2 starts at 104.4 and J10 at 101.2, because a longer name reaches left."""
    tables = find_tables(MYSLINKA)

    borehole = tables[0].columns[0]
    assert abs(borehole - 104.4) <= 4.0 or abs(borehole - 101.2) <= 4.0


def test_a_paragraph_is_not_a_table():
    """Prose is one cell per line at one left edge, which is one column."""
    cells = [
        *_row(700.0, [(70.0, "Inženýrskogeologický průzkum byl proveden v dubnu.")]),
        *_row(688.0, [(70.0, "Zastižené zeminy byly zatříděny podle platné normy.")]),
        *_row(676.0, [(70.0, "Hladina podzemní vody byla naražena ve třech metrech.")]),
        *_row(664.0, [(70.0, "Po ustálení vystoupala o půl metru.")]),
    ]

    assert find_tables(cells) == []


def test_a_two_column_page_layout_is_not_a_table():
    """Two blocks of prose side by side share two positions, and two is not a grid."""
    cells = []
    for index, y in enumerate((700.0, 688.0, 676.0, 664.0)):
        cells += _row(y, [(70.0, f"levý sloupec řádek {index}"),
                          (300.0, f"pravý sloupec řádek {index}")])

    assert find_tables(cells) == []


def test_a_heading_with_indented_text_under_it_is_not_a_table():
    """An indent creates a second position but never a third."""
    cells = [
        *_row(700.0, [(70.0, "3. Inženýrská geologie")]),
        *_row(688.0, [(90.0, "Kopaná sonda byla provedena v dubnu.")]),
        *_row(676.0, [(90.0, "Jádrový vrt dosáhl dvanácti metrů.")]),
        *_row(664.0, [(90.0, "Vzorky byly předány do laboratoře.")]),
    ]

    assert find_tables(cells) == []


def test_two_grids_on_one_page_are_two_tables():
    """A run of rows off the grid ends a table; the next run starts another."""
    cells = []
    for y in (700.0, 690.0, 680.0):
        cells += _row(y, [(70.0, "a"), (150.0, "b"), (230.0, "c")])
    cells += _row(660.0, [(70.0, "Mezitím odstavec textu, který na mřížce neleží.")])
    for y in (600.0, 590.0, 580.0):
        cells += _row(y, [(70.0, "d"), (150.0, "e"), (230.0, "f")])

    tables = find_tables(cells)

    assert len(tables) == 2
    assert [table.shape for table in tables] == [(3, 3), (3, 3)]


def test_a_grid_of_two_rows_is_not_enough():
    """Two rows agreeing is a coincidence these reports produce constantly."""
    cells = []
    for y in (700.0, 690.0):
        cells += _row(y, [(70.0, "a"), (150.0, "b"), (230.0, "c")])

    assert find_tables(cells) == []


def test_rows_come_back_top_first_and_left_to_right():
    """Ordering is what makes the output readable as a table at all."""
    scrambled = [
        Cell(x0=230.0, x1=260.0, y0=690.0, text="f"),
        Cell(x0=70.0, x1=100.0, y0=700.0, text="a"),
        Cell(x0=150.0, x1=180.0, y0=700.0, text="b"),
        Cell(x0=70.0, x1=100.0, y0=690.0, text="d"),
    ]

    rows = group_rows(scrambled)

    assert [[cell.text for cell in row] for row in rows] == [["a", "b"], ["d", "f"]]


def test_a_baseline_that_wobbled_is_still_one_row():
    """pdfminer reports a cell set in a smaller size a point or two lower."""
    cells = _row(700.0, [(70.0, "a"), (150.0, "b")]) + [
        Cell(x0=230.0, x1=260.0, y0=698.5, text="c")
    ]

    rows = group_rows(cells)

    assert len(rows) == 1
    assert [cell.text for cell in rows[0]] == ["a", "b", "c"]


def test_a_page_is_reported_once_however_many_runs_it_broke_into(tmp_path, monkeypatch):
    """A wrapped cell splits a grid, so the page is the unit that stays honest.

    Myslinka page 5 comes back as four runs of what a reader sees as one table.
    Counting runs would report four tables of three to nine rows; counting the
    page reports one page holding 28 rows of eight columns, which is what the
    decision about rebuilding tables actually needs.
    """
    page = []
    for y in (700.0, 690.0, 680.0):
        page += _row(y, [(70.0, "a"), (150.0, "b"), (230.0, "c")])
    page += _row(670.0, [(150.0, "pokračování zalomené buňky")])
    for y in (660.0, 650.0, 640.0):
        page += _row(y, [(70.0, "d"), (150.0, "e"), (230.0, "f")])

    monkeypatch.setattr(table_detect, "page_cells", lambda path: [[], page])

    reports = table_detect.tables_in(tmp_path / "report.pdf")

    assert len(reports) == 1, "one page, one report"
    assert reports[0].page == 2, "page numbers are 1-based"
    assert reports[0].grids == 2, "and it says how many runs it broke into"
    assert reports[0].rows == 6
    assert reports[0].columns == 3


def test_a_page_without_a_table_is_not_reported(tmp_path, monkeypatch):
    """Pages of prose are most of the corpus and must not show up as findings."""
    prose = [
        *_row(700.0, [(70.0, "Inženýrskogeologický průzkum byl proveden v dubnu.")]),
        *_row(688.0, [(70.0, "Zastižené zeminy byly zatříděny podle platné normy.")]),
        *_row(676.0, [(70.0, "Hladina podzemní vody byla naražena ve třech metrech.")]),
    ]
    monkeypatch.setattr(table_detect, "page_cells", lambda path: [prose])

    assert table_detect.tables_in(tmp_path / "report.pdf") == []


def test_a_header_is_reported_as_missing_when_the_top_row_is_short():
    """A reconstruction without a header row cannot label its values."""
    cells = _row(700.0, [(70.0, "a"), (150.0, "b")])
    for y in (690.0, 680.0, 670.0):
        cells += _row(y, [(70.0, "x"), (150.0, "y"), (230.0, "z")])

    tables = find_tables(cells)

    assert len(tables) == 1
    assert tables[0].header is None
