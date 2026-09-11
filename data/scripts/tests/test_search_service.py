"""Tests for the parts of the search service that need no database.

Ranking, fusion and the shape of a hit are pure functions over rows; the SQL
itself is exercised against the real corpus by ``check_pipeline.py``.
"""

from __future__ import annotations

from search_service import (
    RRF_K,
    annotate_across,
    rank_hits,
    reciprocal_rank_fusion,
    snippet,
    to_pgvector,
)


def _row(chunk_id: str, score: float, text: str = "Hladina  podzemní\nvody.") -> dict:
    return {"chunk_id": chunk_id, "document_id": "d", "chunk_index": 0, "chunk_raw": text, "score": score}


def test_rank_hits_carries_only_its_own_branch():
    hits = rank_hits([_row("a", 0.9), _row("b", 0.8), _row("c", 0.7)], "vector", limit=2)
    assert [hit["chunk_id"] for hit in hits] == ["a", "b"]
    assert hits[0]["vector_rank"] == 1 and hits[0]["vector_score"] == 0.9
    assert hits[0]["fts_rank"] is None and hits[0]["fts_score"] is None
    assert hits[0]["rrf_score"] is None
    assert "score" not in hits[0]


def test_fusion_keeps_rank_and_score_of_every_branch():
    vector = [_row("a", 0.9), _row("b", 0.8)]
    fts = [_row("b", 0.5), _row("c", 0.4)]
    hits = reciprocal_rank_fusion({"vector": vector, "fts": fts}, limit=10)

    by_id = {hit["chunk_id"]: hit for hit in hits}
    assert by_id["b"]["vector_rank"] == 2 and by_id["b"]["vector_score"] == 0.8
    assert by_id["b"]["fts_rank"] == 1 and by_id["b"]["fts_score"] == 0.5
    assert by_id["a"]["fts_rank"] is None
    assert by_id["c"]["vector_rank"] is None


def test_fusion_orders_by_summed_reciprocal_rank():
    vector = [_row("a", 0.9), _row("b", 0.8)]
    fts = [_row("b", 0.5), _row("c", 0.4)]
    hits = reciprocal_rank_fusion({"vector": vector, "fts": fts}, limit=2)

    assert [hit["chunk_id"] for hit in hits] == ["b", "a"]
    assert hits[0]["rrf_score"] == 1 / (RRF_K + 2) + 1 / (RRF_K + 1)
    assert hits[1]["rrf_score"] == 1 / (RRF_K + 1)


def test_annotate_across_fills_in_the_other_branch():
    vector = [_row("a", 0.9), _row("b", 0.8)]
    fts = [_row("b", 0.5)]
    hits = rank_hits(fts, "fts", limit=5)
    annotate_across(hits, {"vector": vector, "fts": fts})
    assert hits[0]["vector_rank"] == 2 and hits[0]["vector_score"] == 0.8
    assert hits[0]["fts_rank"] == 1


def test_snippet_collapses_whitespace_and_cuts():
    assert snippet("Hladina  podzemní\nvody.") == "Hladina podzemní vody."
    assert snippet("x" * 400, chars=10) == "x" * 10
    assert snippet(None) == ""


def test_to_pgvector_formats_a_literal():
    assert to_pgvector([1.0, 0.5]) == "[1.000000,0.500000]"
