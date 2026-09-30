"""Find the tables a PDF page draws but its text layer does not say it draws.

`pdf_pages` reads each page through pdfminer's ``TextConverter``, which flattens
the layout to a string. A table survives that as a column of cells, one per line,
with nothing tying a value to its heading: the borehole table on page 5 of
Myslinka comes out as ``Sonda / č. / Hloubka / sondy / (m) / vzorek pro / …``
followed by a bare column of depths. A reader cannot answer "how deep was the
sample from J4" from that, and a model reading the chunk could invent the answer -
the same reason extraction may not infer and no model writes SQL here.

The geometry that was thrown away is still in the PDF. pdfminer's
``extract_pages`` gives every text line a bounding box, and on that page the
eight header cells share one baseline at eight stable x positions that the data
rows land on too. This module measures that, and only measures it: nothing here
feeds the Markdown, so no version moves and nothing is re-embedded. What it
produces is the number that decides whether reconstructing tables is worth a paid
re-run of the corpus - above all, how many tables sit in the body rather than in
an annex whose chunks carry no vector anyway.

Known limitation, left for whoever does the reconstruction: a cell wrapped over
two lines is reported as its own row, because splitting a row from a wrapped cell
needs the column widths this pass only estimates.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# How far apart two text lines may sit and still be one row. Body text in these
# reports is set with about 10pt of leading and table rows with less, so half a
# line is generous for a baseline that wobbled and tight enough not to fuse two
# rows. Measured on Myslinka page 5, whose header cells share y0 exactly.
_ROW_TOLERANCE = 3.0

# How far apart two left edges may sit and still be one column. pdfminer reports
# x0 to a tenth of a point and the same column varies by a couple of points when
# its cells are set in different sizes: the borehole column on Myslinka page 5
# reads 104.4 for J2 and 101.2 for J10, because a three-character name starts
# further left.
_COLUMN_TOLERANCE = 4.0

# Positions are clustered by proximity rather than compared to one representative,
# because a column of wrapped cells drifts across more than the tolerance in
# total: 174.3, 178.9 and 183.6 on Myslinka page 5 are one column whose ends are
# 9 points apart. Single linkage alone would then chain across a page of ragged
# text, so a cluster may not grow wider than this - about two characters.
_COLUMN_MAX_SPREAD = 12.0

# What makes a grid rather than a coincidence. Two rows sharing two positions is
# ordinary prose - an indented paragraph under a heading does that - so the bar
# is three of each. Deliberately low: this pass is meant to find candidates for a
# human to look at, and --tables prints the size of every one it finds.
_MIN_ROWS = 3
_MIN_COLUMNS = 3


@dataclass(frozen=True)
class Cell:
    """One piece of text on a page, with the box pdfminer measured for it."""

    x0: float
    x1: float
    y0: float
    text: str


@dataclass(frozen=True)
class Table:
    """A grid found on one page.

    ``rows`` holds the cells of each row, ordered left to right, top row first.
    ``columns`` holds the left edges the rows agreed on.
    """

    columns: list[float]
    rows: list[list[Cell]]

    @property
    def shape(self) -> tuple[int, int]:
        """Return (rows, columns)."""
        return len(self.rows), len(self.columns)

    @property
    def header(self) -> list[str] | None:
        """Return the top row's text when it fills every column, else None.

        A table whose first row is short is one whose heading pdfminer wrapped or
        never had; the distinction matters because a reconstruction without a
        header row cannot label its values.
        """
        if not self.rows:
            return None
        top = self.rows[0]
        return [cell.text for cell in top] if len(top) == len(self.columns) else None


def group_rows(cells: list[Cell], tolerance: float = _ROW_TOLERANCE) -> list[list[Cell]]:
    """Group cells into rows by baseline, top of the page first.

    Cells within ``tolerance`` points of each other belong to one row; each row is
    ordered left to right. Empty text is dropped - it is not a cell.
    """
    present = sorted(
        (cell for cell in cells if cell.text.strip()), key=lambda cell: -cell.y0
    )
    rows: list[list[Cell]] = []
    for cell in present:
        if rows and abs(rows[-1][0].y0 - cell.y0) <= tolerance:
            rows[-1].append(cell)
        else:
            rows.append([cell])
    return [sorted(row, key=lambda cell: cell.x0) for row in rows]


def _cluster(positions: list[float], tolerance: float) -> list[list[float]]:
    """Group sorted positions into columns, capped at ``_COLUMN_MAX_SPREAD`` wide."""
    clusters: list[list[float]] = []
    for position in sorted(positions):
        if (
            clusters
            and position - clusters[-1][-1] <= tolerance
            and position - clusters[-1][0] <= _COLUMN_MAX_SPREAD
        ):
            clusters[-1].append(position)
        else:
            clusters.append([position])
    return clusters


def _columns_of(rows: list[list[Cell]], tolerance: float) -> list[float]:
    """Return the left edges shared by at least ``_MIN_ROWS`` of ``rows``.

    A column counts once per row however many cells that row puts in it, so a
    single row of many short words cannot invent a column on its own.
    """
    clusters = _cluster([cell.x0 for row in rows for cell in row], tolerance)

    columns: list[float] = []
    for cluster in clusters:
        low, high = cluster[0], cluster[-1]
        shared = sum(1 for row in rows if any(low <= cell.x0 <= high for cell in row))
        if shared >= _MIN_ROWS:
            columns.append(sum(cluster) / len(cluster))
    return columns


def _column_of(cell: Cell, columns: list[float]) -> float | None:
    """Return the column ``cell`` sits in, or None when it sits between columns."""
    for position in columns:
        if abs(cell.x0 - position) <= _COLUMN_MAX_SPREAD:
            return position
    return None


def _is_header_row(row: list[Cell], columns: list[float]) -> bool:
    """Return whether ``row`` can be the heading of a grid with these columns.

    A heading does not have to land on the columns its data lands on: header
    cells are usually centred in their cell and the values under them are
    left-aligned, so "Sonda" starts at 95.6 where "J1" starts at 104.4. Position
    is therefore not the test. What a heading cannot be is prose, and prose at
    that place on the page is one long line - that is, one cell.

    The looseness is deliberate and costs little: a two-word line above a table
    can be adopted wrongly, and ``--tables`` prints the text it adopted so a
    reader sees it.
    """
    return 2 <= len(row) <= len(columns)


def find_tables(
    cells: list[Cell],
    *,
    min_rows: int = _MIN_ROWS,
    min_columns: int = _MIN_COLUMNS,
) -> list[Table]:
    """Return the grids on one page.

    The page's columns are the left edges at least ``min_rows`` rows agree on, and
    a grid is a run of consecutive rows that put **all** their text on those
    columns and put it in at least two of them. Filling many columns is not the
    test: a borehole row that fills two of eight is still part of the table, and
    requiring three of them split Myslinka's one table into four. What a row of
    the table cannot do is put text between the columns, which is exactly what a
    line of prose does - and a line of prose is one cell anyway. Runs shorter than
    ``min_rows`` are dropped. The row directly above a run joins it when it could
    be the heading; see ``_is_header_row``.
    """
    rows = group_rows(cells)
    if len(rows) < min_rows:
        return []

    columns = _columns_of(rows, _COLUMN_TOLERANCE)
    if len(columns) < min_columns:
        return []

    def _on_grid(row: list[Cell]) -> bool:
        found = [_column_of(cell, columns) for cell in row]
        if any(position is None for position in found):
            return False
        return len(set(found)) >= 2

    grid = [index for index, row in enumerate(rows) if _on_grid(row)]
    runs: list[list[int]] = []
    for index in grid:
        if runs and index == runs[-1][-1] + 1:
            runs[-1].append(index)
        else:
            runs.append([index])

    tables: list[Table] = []
    taken: set[int] = set()
    for run in runs:
        if len(run) < min_rows:
            continue
        above = run[0] - 1
        if above >= 0 and above not in taken and _is_header_row(rows[above], columns):
            run = [above, *run]
        taken.update(run)
        tables.append(Table(columns=list(columns), rows=[rows[index] for index in run]))
    return tables


def page_cells(path: Path) -> list[list[Cell]]:
    """Return the cells of every page of a PDF, one list per page.

    The same engine as ``extract_reports.pdf_pages`` - there is still only one -
    read through the layout API instead of the text one. This must not become a
    second source of text for the Markdown; it is here to count.
    """
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTTextBox, LTTextLine

    pages: list[list[Cell]] = []
    for layout in extract_pages(path, laparams=LAParams()):
        cells = [
            Cell(x0=line.x0, x1=line.x1, y0=line.y0, text=line.get_text().strip())
            for box in layout
            if isinstance(box, LTTextBox)
            for line in box
            if isinstance(line, LTTextLine)
        ]
        pages.append(cells)
    return pages


@dataclass(frozen=True)
class PageReport:
    """What one page holds, which is the unit worth counting.

    A grid breaks wherever a cell wrapped onto a line of its own: a continuation
    line puts one value on one column, and a row on one column cannot be told
    apart from a line of prose. Myslinka page 5 therefore comes back as four runs
    of what a reader sees as one table. Per-page totals are immune to that, and
    the page is also the unit the decision needs, because whether a page is prose
    or a form is what says if its chunks carry a vector at all.
    """

    page: int
    columns: int
    rows: int
    grids: int
    header: list[str] | None


def tables_in(path: Path) -> list[PageReport]:
    """Return one report per page of ``path`` that holds a table, pages 1-based."""
    reports: list[PageReport] = []
    for number, cells in enumerate(page_cells(path), start=1):
        tables = find_tables(cells)
        if not tables:
            continue
        header = next((table.header for table in tables if table.header), None)
        reports.append(
            PageReport(
                page=number,
                columns=max(len(table.columns) for table in tables),
                rows=sum(len(table.rows) for table in tables),
                grids=len(tables),
                header=header,
            )
        )
    return reports
