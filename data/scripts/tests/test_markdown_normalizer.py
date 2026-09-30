"""Tests for the parts of normalisation that can lose text silently.

Deleting a repeated line is the one step here with no downstream signal: a
threshold meant for pagination can reach real content, and the Markdown that
comes out looks perfectly well formed either way.
"""

from __future__ import annotations

from markdown_normalizer import _heuristic_headings, _signature, normalize_markdown


def _document(furniture_repeats: int) -> str:
    """Build a small report with a contents page, headings and a running header."""
    header = "GEOLOGICKY PRUZKUM SPOLECNOST ZAHLAVI STRANY"
    contents = [
        "Obsah",
        "1. Uvod ..... 1",
        "2. Metodika pruzkumu ..... 2",
        "3. Zaver ..... 3",
        "",
    ]
    # The chapters have to carry real weight: the loss is measured against the
    # whole document, so a body of three sentences makes even the contents page
    # look like a catastrophic deletion.
    prose = (
        "Vrtne prace byly provedeny jadrovym vrtanim v obdobi od brezna do dubna. "
        "Zastizene zeminy byly zatrideny podle platne normy a odebrane vzorky byly "
        "predany do akreditovane laboratore. Hladina podzemni vody byla naraze na "
        "v hloubce tri metry pod urovni terenu a po ustaleni vystoupala o pul metru."
    )
    body = [
        "1. Uvod",
        prose,
        "",
        "2. Metodika pruzkumu",
        prose,
        "",
        "3. Zaver",
        prose,
        "",
    ]
    return "\n".join(contents + body + [header] * furniture_repeats) + "\n"


def test_a_repeated_header_is_removed():
    """The ordinary case: pagination goes, headings stay."""
    markdown, stats = normalize_markdown(_document(4), page_count=4)
    assert stats.headings > 0
    assert stats.furniture_dropped == 4
    assert stats.furniture_kept is False
    assert "ZAHLAVI STRANY" not in markdown


def test_headings_survive_a_header_that_would_blow_the_loss_budget():
    """When furniture removal is what trips the guard, retry without it.

    Discarding the whole normalisation costs every chunk its section citation -
    Sedmirohé went into the corpus with 523 chunks and no citation at all,
    despite fifteen headings having been recovered correctly. Keeping the
    running header instead only costs noise, and check_pipeline already reports
    that noise as "zbytky konverze".
    """
    markdown, stats = normalize_markdown(_document(40), page_count=4)

    assert stats.furniture_kept is True, "the relaxed pass should have been used"
    assert stats.headings > 0, "the headings are the whole point of retrying"
    assert stats.furniture_dropped == 0
    assert "ZAHLAVI STRANY" in markdown, "the header stays, and is reported as noise"


def test_removals_say_what_went_and_why():
    """The record is grouped by the rule that matched, not line by line."""
    _, stats = normalize_markdown(_document(4), page_count=4)

    reasons = {removal.reason for removal in stats.removals}
    assert reasons == {"furniture", "contents"}

    furniture = next(item for item in stats.removals if item.reason == "furniture")
    assert furniture.lines == 4
    assert "ZAHLAVI" in furniture.detail
    assert "práh" in furniture.detail


def test_a_column_of_measurements_is_not_a_running_header():
    """Laboratory tables repeat "<0," down every page, and those are data.

    check_pipeline already refuses to report such a line as leftover conversion
    for exactly this reason; deletion was not applying the same rule, and 852
    lines of measurements were being removed as pagination across the corpus.
    """
    assert _signature("<0,") is None
    assert _signature("311,") is None
    assert _signature("207.") is None

    assert _signature("Objednatel:") is not None
    assert _signature("Dokument č.") is not None
    assert _signature("GEOLOGICKY PRUZKUM ZAHLAVI") is not None


def _prose(marker: str) -> list[str]:
    """Return a paragraph long enough to separate two headings."""
    return [
        f"Vrtne prace {marker} byly provedeny jadrovym vrtanim v obdobi od brezna.",
        f"Zastizene zeminy {marker} byly zatrideny podle platne normy.",
        f"Hladina podzemni vody {marker} byla narazena v hloubce tri metry.",
        "",
    ]


def test_a_contents_page_without_dot_leaders_does_not_become_the_headings():
    """The outline that wins has to be the one with the report under it.

    A contents page whose entries carry no dot leaders is invisible to
    _extract_toc, so it reaches the heuristic as a flawless outline, sits first
    and used to win on the tie. Mladá Boleslav went through with its six body
    headings unmarked, five empty sections and "6. Závěr" spanning 788 lines.
    """
    lines = [
        "OBSAH",
        "1. Uvod",
        "2. Metodika pruzkumu",
        "3. Zaver",
        "",
        "1. Uvod",
        *_prose("uvodu"),
        "2. Metodika pruzkumu",
        *_prose("metodiky"),
        "3. Zaver",
        *_prose("zaveru"),
    ]

    headings = _heuristic_headings(lines)

    assert headings == {5, 10, 15}, "the body chain, not the contents page"


def test_a_chain_seeded_on_an_annex_list_loses_to_the_body():
    """Equal length has to go to the later start.

    Čejetice lists "1. Dokumentace sond" and "2. Situace sond" above the report
    and then carries on into the real chapters, so that chain is as long as the
    body's and spread out just as far - the gap filter cannot tell them apart.
    """
    lines = [
        "1. Dokumentace sond",
        "2. Situace sond",
        "",
        "1. Uvod",
        *_prose("uvodu"),
        "2. Prirodni pomery",
        *_prose("pomeru"),
        "3. Zaver",
        *_prose("zaveru"),
    ]

    headings = _heuristic_headings(lines)

    assert headings == {3, 8, 13}, "the chapters, not the list of annexes"


def test_a_chapter_numbered_1_1_is_still_a_chapter():
    """Some reports number their chapters 1.1, 1.2, 1.3 and never write a bare 1.

    Without a chain seeded at 1.1 the only outline ZZ_Opava - Zimní stadion
    offered was its annex list, and the annex list won. The chain may not then
    drop back to depth one, or it runs on into that same list.
    """
    lines = [
        "1.1 UVOD A ROZSAH REALIZOVANYCH PRACI",
        *_prose("uvodu"),
        "1.2 VYHODNOCENI PRACI",
        *_prose("vyhodnoceni"),
        "1.3 ZAVER",
        *_prose("zaveru"),
        "2. Podrobna situace zajmove lokality",
        "3. Geologicke profily sond",
        "4. Zprava vrtnych praci",
    ]

    headings = _heuristic_headings(lines)

    assert headings == {0, 5, 10}, "the three chapters, none of the annex list"
