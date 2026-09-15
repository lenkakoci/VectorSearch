"""Tests for checking an answer against the sources it cites.

No API and no database: the answer arrives as plain dicts, the sources as the
context builder would have numbered them.
"""

from __future__ import annotations

from citation_check import (
    INVALID_SOURCE,
    NUMBER_UNSUPPORTED,
    QUOTE_NOT_FOUND,
    UNSUPPORTED,
    VERIFIED,
    check_answer,
    check_statement,
    final_status,
    numbers_in,
)

SOURCES = [
    {
        "id": 1,
        "title": "ROUDNO – REKREAČNÍ AREÁL – HG POSUDEK",
        "municipality": "Roudno",
        "report_date": "2016-03-23",
        "chunk_raw": "Pro  zabudování  tepelného  čerpadla  byly  navrženy  vrtné  práce –"
        " cca 12 ks hlubokých vrtů o předpokládané hloubce okolo 80 m (celkem 960 m).",
    },
    {
        "id": 2,
        "title": "Průzkum Lednice",
        "municipality": "Lednice",
        "chunk_raw": "Hladina  podzemní  vody  ustálená  se  vyskytovala  v rozmezí  od  0,4  –  1,0  m"
        " pod  povrchem  terénu.",
    },
]
BY_ID = {source["id"]: source for source in SOURCES}


def _statement(text: str, ids: list[int], quotes: list[str]) -> dict:
    return {"text": text, "source_ids": ids, "quotes": quotes}


def test_a_quote_survives_doubled_spaces_and_a_different_dash():
    statement = _statement(
        "Navrženo bylo cca 12 ks vrtů o hloubce okolo 80 m.",
        [1],
        ["cca 12 ks hlubokých vrtů o předpokládané hloubce okolo 80 m"],
    )
    assert check_statement(statement, BY_ID)["check"] == VERIFIED


def test_a_quote_that_is_not_in_the_cited_source_is_caught():
    statement = _statement("Hloubka je 80 m.", [1], ["hloubka okolo 100 m"])
    checked = check_statement(statement, BY_ID)
    assert checked["check"] == QUOTE_NOT_FOUND
    assert "100 m" in checked["note"]


def test_an_unknown_source_id_is_caught():
    statement = _statement("Cokoli.", [7], ["cca 12 ks"])
    assert check_statement(statement, BY_ID)["check"] == INVALID_SOURCE


def test_a_sentence_without_a_source_or_quote_is_unsupported():
    assert check_statement(_statement("Bez opory.", [], []), BY_ID)["check"] == UNSUPPORTED
    assert check_statement(_statement("Bez citátu.", [1], []), BY_ID)["check"] == UNSUPPORTED


def test_a_number_the_sources_do_not_state_is_caught():
    statement = _statement(
        "Navrženo bylo 14 vrtů o hloubce okolo 80 m.",
        [1],
        ["cca 12 ks hlubokých vrtů o předpokládané hloubce okolo 80 m"],
    )
    checked = check_statement(statement, BY_ID)
    assert checked["check"] == NUMBER_UNSUPPORTED
    assert "14" in checked["note"]


def test_numbers_are_read_as_a_report_writes_them():
    assert numbers_in("hladina 0,4 – 1,0 m a norma ČSN 75 9010") == ["0,4", "1,0", "75", "9010"]
    statement = _statement("Hladina byla v rozmezí 0,4 až 1,0 m.", [2], ["v rozmezí od 0,4 – 1,0 m"])
    assert check_statement(statement, BY_ID)["check"] == VERIFIED


def test_a_digit_in_a_borehole_name_is_not_read_as_a_quantity():
    # HV1 and J16 are names; the 1 and the 16 are not claims about a value.
    assert numbers_in("ve vrtu HV1 a sondě J16 bylo 9,0 mg/kg") == ["9,0"]
    sources = {1: {"id": 1, "chunk_raw": "Koncentrace benzenu stouply na 2 215 µg/l."}}
    statement = _statement(
        "Ve vrtu HV1 byla koncentrace 2 215 µg/l.",
        [1],
        ["stouply na 2 215"],
    )
    assert check_statement(statement, sources)["check"] == VERIFIED


def test_a_number_inside_a_longer_number_does_not_count_as_support():
    sources = {1: {"id": 1, "chunk_raw": "Celková metráž byla 960 m."}}
    statement = _statement("Hloubka je 96 m.", [1], ["Celková metráž byla 960 m"])
    assert check_statement(statement, sources)["check"] == NUMBER_UNSUPPORTED


def test_numbers_separated_by_spaces_in_a_table_are_found():
    # An annex table prints one value after another: 25, 24 and 41 stand apart.
    sources = {
        1: {
            "id": 1,
            "chunk_raw": "Přílohy J16 J22 J20 0,50-2,50 mg / kg sušiny 9,0 < 0,5 24 < 0,1 25 24 41",
        }
    }
    statement = _statement(
        "Ve vzorku J16 bylo zjištěno 24 mg/kg chromu, 25 mg/kg niklu a 41 mg/kg vanadu.",
        [1],
        ["9,0 < 0,5 24 < 0,1 25 24 41"],
    )
    assert check_statement(statement, sources)["check"] == VERIFIED


def test_a_thousand_written_with_a_space_still_matches():
    sources = {1: {"id": 1, "chunk_raw": "koncentrace stouply na 2 215 µg/l"}}
    statement = _statement("Koncentrace stoupla na 2215 µg/l.", [1], ["stouply na 2 215"])
    assert check_statement(statement, sources)["check"] == VERIFIED


def test_a_number_from_the_document_header_counts_as_evidence():
    # The parcel number is in the title the model sees with every source.
    sources = {
        1: {
            "id": 1,
            "title": "průzkumný hydrogeologický vrt STAV P.P.Č. 106/2 ZÁVĚREČNÁ ZPRÁVA",
            "municipality": "Úbislavice",
            "chunk_raw": "Hydrograficky leží zájmové území v povodí IV. řádu Úlibický potok"
            " (číslo hydrol. pořadí 1-04-02-014).",
        }
    }
    statement = _statement(
        "Vrt na parcele č. 106/2 leží v povodí Úlibického potoka, číslo 1-04-02-014.",
        [1],
        ["v povodí IV. řádu Úlibický potok"],
    )
    assert check_statement(statement, sources)["check"] == VERIFIED


def test_a_page_number_does_not_support_a_quantity():
    # Pages are small integers like the quantities the check protects, so they
    # stay out of the evidence; the instructions keep them out of sentences.
    sources = {
        1: {
            "id": 1,
            "section": "5.1 Návrh vrtů",
            "page_from": 14,
            "page_to": 15,
            "chunk_raw": "Vrty budou hluboké 80 m.",
        }
    }
    statement = _statement("Navrženo je 14 vrtů.", [1], ["Vrty budou hluboké 80 m"])
    assert check_statement(statement, sources)["check"] == NUMBER_UNSUPPORTED


def test_check_answer_summarises_and_lists_cited_sources():
    statements = [
        _statement("Vrtů je cca 12 ks.", [1], ["cca 12 ks hlubokých vrtů"]),
        _statement("Voda je 3 m pod terénem.", [2], ["v rozmezí od 0,4 – 1,0 m"]),
    ]
    checked, summary = check_answer(statements, SOURCES)
    assert [item["check"] for item in checked] == [VERIFIED, NUMBER_UNSUPPORTED]
    assert summary["verified"] == 1
    assert summary["flagged"] == 1
    assert summary["cited_sources"] == [1, 2]


def test_status_is_downgraded_when_a_sentence_fails():
    statements = [{"check": VERIFIED}, {"check": QUOTE_NOT_FOUND}]
    assert final_status("answered", statements) == "partial"
    assert final_status("answered", [{"check": QUOTE_NOT_FOUND}]) == "insufficient"
    assert final_status("answered", []) == "insufficient"
    assert final_status("insufficient", []) == "insufficient"
    assert final_status("answered", [{"check": VERIFIED}]) == "answered"
