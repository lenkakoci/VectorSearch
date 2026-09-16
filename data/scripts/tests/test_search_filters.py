"""Tests for the metadata filter vocabulary.

``search_filters.py`` composes SQL only from its fixed vocabulary and passes
values as parameters, so these tests check the shape of the fragment and the
parameters rather than a database result. No API, no database.
"""

from __future__ import annotations

from datetime import date

from search_filters import Filters, build_filters, column_expression, parse_query


def test_parse_query_splits_prefixes_from_text():
    text, filters = parse_query('autor:Poul obec:"Lednice" hladina vody')
    assert text == "hladina vody"
    assert filters.author == "Poul"
    assert filters.municipality == "Lednice"


def test_unknown_prefix_stays_in_text():
    text, filters = parse_query("hloubka:3 vrt")
    assert text == "hloubka:3 vrt"
    assert filters.is_empty()


def test_single_text_value_uses_ilike():
    sql, params = build_filters(author="Poul").where()
    assert sql.strip() == "AND d.author ILIKE %s"
    assert params == ["%Poul%"]


def test_many_text_values_use_ilike_any():
    sql, params = build_filters(author=["Poul", "Bičík"]).where()
    assert sql.strip() == "AND d.author ILIKE ANY(%s)"
    assert params == [["%Poul%", "%Bičík%"]]


def test_list_of_one_collapses_to_the_string():
    assert build_filters(author=["Poul"]) == build_filters(author="Poul")


def test_blank_and_duplicate_values_are_dropped():
    filters = build_filters(municipality=["Lednice", " ", "Lednice", "Roudno"])
    assert filters.municipality == ("Lednice", "Roudno")


def test_content_kind_accepts_aliases():
    assert build_filters(content_kind="příloha").content_kind == "annex"
    assert build_filters(content_kind="TELO").content_kind == "prose"
    _, filters = parse_query("druh:annex sonda S-2")
    assert filters.content_kind == "annex"


def test_unknown_content_kind_is_ignored():
    assert build_filters(content_kind="tabulka").content_kind is None


def test_content_kind_only_applies_to_chunk_queries():
    filters = build_filters(content_kind="annex", author="Poul")
    chunk_sql, chunk_params = filters.where(scope="chunks")
    doc_sql, doc_params = filters.where(scope="documents")
    assert "c.content_kind = %s" in chunk_sql
    assert chunk_params == ["%Poul%", "annex"]
    assert "content_kind" not in doc_sql
    assert doc_params == ["%Poul%"]


def test_date_bounds_widen_to_the_edge():
    filters = build_filters(date_from="2019", date_to="2019-09")
    assert filters.date_from == date(2019, 1, 1)
    assert filters.date_to == date(2019, 9, 30)


def test_document_ids_must_be_uuids():
    good = "30804a28-36a8-5080-b306-a2c737f7cd47"
    filters = build_filters(document_ids=[good, "Roudno"])
    assert filters.document_ids == (good,)


def test_inline_prefix_wins_over_flag_on_merge():
    _, inline = parse_query("autor:Poul voda")
    merged = inline.merge(build_filters(author="Bičík", municipality="Lednice"))
    assert merged.author == "Poul"
    assert merged.municipality == "Lednice"


def test_describe_lists_alternatives():
    filters = build_filters(author=["Poul", "Bičík"], content_kind="annex", date_from="2019")
    assert filters.describe() == "autor ~ 'Poul' | 'Bičík', od 2019-01-01, část = annex"


def test_as_dict_lists_only_what_is_restricted():
    filters = build_filters(author="Poul", municipality=["Lednice", "Roudno"], date_from="2019")
    assert filters.as_dict() == {
        "author": "Poul",
        "municipality": ["Lednice", "Roudno"],
        "date_from": "2019-01-01",
    }
    assert build_filters().as_dict() == {}


def test_empty_filters_produce_no_clause():
    assert Filters().where() == ("", [])
    assert Filters().describe() == ""


def test_column_expression_matches_the_filter_vocabulary():
    assert column_expression("municipality") == "d.extraction_json->>'municipality'"
