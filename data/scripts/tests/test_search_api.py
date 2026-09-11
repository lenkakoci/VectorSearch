"""Tests for the HTTP layer, with the search service replaced.

The routes are thin: validate, call the service, serialise. These tests pin
that contract - what reaches the service and what comes back - without a
database. The SQL is exercised by ``check_pipeline.py`` against the corpus.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import pytest
from fastapi.testclient import TestClient

import search_api
from search_service import EmbeddingUnavailable, SearchResult


def _hit(**overrides):
    hit = {
        "chunk_id": "9d4a9a1e-1111-4111-8111-111111111111",
        "document_id": "30804a28-36a8-5080-b306-a2c737f7cd47",
        "chunk_index": 38,
        "section": "HG POSUDEK > 5. REALIZACE TEPELNÝCH ČERPADEL",
        "content_kind": "prose",
        "page_from": 14,
        "page_to": None,
        "chunk_raw": "Technické parametry vrtů pro tepelné čerpadlo",
        "snippet": "Technické parametry vrtů pro tepelné čerpadlo",
        "headline": "Technické parametry <mark>vrtů</mark> pro <mark>tepelné</mark> <mark>čerpadlo</mark>",
        "lexical_match": True,
        "title": "ROUDNO – HG POSUDEK",
        "author": "RNDr. Karel Makowetz",
        "organization": "UNIGEO, a.s.",
        "municipality": "Roudno",
        "report_type": "hydrogeologický průzkum",
        "report_date": date(2016, 3, 23),
        "locality": "Roudno",
        "vector_rank": None,
        "vector_score": None,
        "fts_rank": 1,
        "fts_score": 0.0743,
        "rrf_score": None,
    }
    hit.update(overrides)
    return hit


def _result(query, mode, limit=10, hits=None):
    return SearchResult(
        query=query, mode=mode, limit=limit, fetch=limit, hits=hits if hits is not None else [_hit()],
        debug={"tsquery": {"czech": "'vrt'", "czech_literal": "'vrty'"}, "filters": ""},
    )


@pytest.fixture
def client(monkeypatch):
    @contextmanager
    def fake_connection():
        yield object()

    monkeypatch.setattr(search_api, "connection", fake_connection)
    return TestClient(search_api.app)


def test_search_returns_hits_and_passes_filters(client, monkeypatch):
    seen = {}

    def fake_run_search(conn, query, mode, filters, limit, settings):
        seen.update(query=query, mode=mode, filters=filters, limit=limit)
        return _result(query, mode, limit)

    monkeypatch.setattr(search_api, "run_search", fake_run_search)
    response = client.post(
        "/api/search",
        json={
            "query": "autor:Poul vrty pro tepelné čerpadlo",
            "mode": "fts",
            "limit": 3,
            "filters": {"municipalities": ["Roudno", "Lednice"], "content_kind": "annex", "date_from": "2019"},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "fts"
    assert body["hits"][0]["headline"].count("<mark>") == 3
    assert body["hits"][0]["report_date"] == "2016-03-23"
    assert body["debug"]["tsquery"]["czech"] == "'vrt'"

    assert seen["query"] == "vrty pro tepelné čerpadlo"
    assert seen["limit"] == 3
    assert seen["filters"].author == "Poul"
    assert seen["filters"].municipality == ("Roudno", "Lednice")
    assert seen["filters"].content_kind == "annex"
    assert seen["filters"].date_from == date(2019, 1, 1)


def test_search_rejects_unknown_mode_and_empty_query(client):
    assert client.post("/api/search", json={"query": "voda", "mode": "graph"}).status_code == 422
    assert client.post("/api/search", json={"query": ""}).status_code == 422
    assert client.post("/api/search", json={"query": "autor:Poul"}).status_code == 422


def test_embedding_failure_maps_to_503(client, monkeypatch):
    def failing(*args, **kwargs):
        raise EmbeddingUnavailable("ClientError: 429")

    monkeypatch.setattr(search_api, "run_search", failing)
    response = client.post("/api/search", json={"query": "voda", "mode": "vector"})
    assert response.status_code == 503
    assert "Fulltext" in response.json()["detail"]


def test_compare_returns_every_mode(client, monkeypatch):
    def fake_compare(conn, query, filters, limit, settings):
        return {mode: _result(query, mode, limit) for mode in ("fts", "vector", "hybrid")}

    monkeypatch.setattr(search_api, "compare", fake_compare)
    response = client.post("/api/compare", json={"query": "hladina podzemní vody", "limit": 5})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["query"] == "hladina podzemní vody"
    assert set(body) == {"query", "fts", "vector", "hybrid"}
    assert body["hybrid"]["mode"] == "hybrid"


def test_context_validates_uuid_and_reports_missing(client, monkeypatch):
    monkeypatch.setattr(search_api, "get_document", lambda conn, document_id: None)
    assert client.get("/api/chunks/not-a-uuid/3/context").status_code == 422
    assert client.get("/api/chunks/30804a28-36a8-5080-b306-a2c737f7cd47/3/context").status_code == 404


def test_context_returns_neighbours_in_order(client, monkeypatch):
    monkeypatch.setattr(search_api, "get_document", lambda conn, document_id: {"title": "Roudno"})
    monkeypatch.setattr(
        search_api,
        "neighbours",
        lambda conn, document_id, chunk_index, before, after: [
            {"chunk_index": index, "section": "s", "content_kind": "prose", "page_from": None,
             "page_to": None, "chunk_raw": "t", "is_hit": index == chunk_index}
            for index in range(chunk_index - before, chunk_index + after + 1)
        ],
    )
    response = client.get("/api/chunks/30804a28-36a8-5080-b306-a2c737f7cd47/3/context?before=2&after=1")
    assert response.status_code == 200
    chunks = response.json()["chunks"]
    assert [chunk["chunk_index"] for chunk in chunks] == [1, 2, 3, 4]
    assert [chunk["is_hit"] for chunk in chunks] == [False, False, True, False]


def test_document_detail_exposes_extraction(client, monkeypatch):
    monkeypatch.setattr(
        search_api,
        "get_document",
        lambda conn, document_id: {
            "id": document_id, "source_file": "PDFs/Roudno.pdf", "title": "Roudno", "report_type": None,
            "locality": None, "report_date": date(2016, 3, 23), "author": None, "client": None,
            "summary": "shrnutí", "extraction_json": {"key_findings": ["a"]}, "extraction_model": "gemini",
            "extraction_schema_version": 1, "chunks": 53,
        },
    )
    response = client.get("/api/documents/30804a28-36a8-5080-b306-a2c737f7cd47")
    assert response.status_code == 200
    assert response.json()["extraction"] == {"key_findings": ["a"]}
    assert response.json()["chunks"] == 53


def test_health_reports_counts(client, monkeypatch):
    monkeypatch.setattr(
        search_api, "corpus_counts", lambda conn: {"documents": 16, "chunks": 2040, "chunks_with_vector": 1025}
    )
    assert client.get("/api/health").json() == {
        "status": "ok", "documents": 16, "chunks": 2040, "chunks_with_vector": 1025,
    }
