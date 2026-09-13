"""Tests for the HTTP layer, with the search service replaced.

The routes are thin: validate, call the service, serialise. These tests pin
that contract - what reaches the service and what comes back - without a
database. The SQL is exercised against the corpus by ``eval_retrieval.py``.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import pytest
from fastapi.testclient import TestClient

import search_api
from rerank_service import RerankUnavailable
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


def _result(query, mode, limit=10, hits=None, debug=None):
    return SearchResult(
        query=query, mode=mode, limit=limit, fetch=limit, hits=hits if hits is not None else [_hit()],
        debug=debug or {"tsquery": {"czech": "'vrt'", "czech_literal": "'vrty'"}, "filters": ""},
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
    assert body["hits"][0]["rerank_grade"] is None
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


def test_rerank_failure_in_single_mode_maps_to_503(client, monkeypatch):
    def failing(*args, **kwargs):
        raise RerankUnavailable("ServerError: 503")

    monkeypatch.setattr(search_api, "run_search", failing)
    response = client.post("/api/search", json={"query": "voda", "mode": "rerank"})
    assert response.status_code == 503
    assert "Reranking" in response.json()["detail"]


def test_compare_returns_every_mode_without_rerank_by_default(client, monkeypatch):
    seen = {}

    def fake_compare(conn, query, filters, limit, settings, **kwargs):
        seen.update(kwargs)
        return {mode: _result(query, mode, limit) for mode in kwargs["modes"]}

    monkeypatch.setattr(search_api, "compare", fake_compare)
    response = client.post("/api/compare", json={"query": "hladina podzemní vody", "limit": 5})
    assert response.status_code == 200, response.text
    body = response.json()
    assert seen["modes"] == ("fts", "vector", "hybrid")
    assert body["query"] == "hladina podzemní vody"
    assert body["hybrid"]["mode"] == "hybrid"
    assert body["rerank"] is None


def test_compare_with_rerank_adds_the_graded_column(client, monkeypatch):
    seen = {}

    def fake_compare(conn, query, filters, limit, settings, **kwargs):
        seen.update(kwargs)
        results = {mode: _result(query, mode, limit) for mode in kwargs["modes"]}
        results["rerank"] = _result(
            query, "rerank", limit,
            hits=[_hit(rerank_grade=3, rerank_reason="Uvádí počet a hloubku vrtů.", candidate_rank=2)],
            debug={"rerank": {"candidates": 40, "passed": 3, "min_grade": 2}},
        )
        return results

    monkeypatch.setattr(search_api, "compare", fake_compare)
    response = client.post("/api/compare", json={"query": "vrty pro tepelné čerpadlo", "rerank": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert seen["modes"] == ("fts", "vector", "hybrid", "rerank")
    hit = body["rerank"]["hits"][0]
    assert (hit["rerank_grade"], hit["candidate_rank"]) == (3, 2)
    assert body["rerank"]["debug"]["rerank"]["passed"] == 3


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
