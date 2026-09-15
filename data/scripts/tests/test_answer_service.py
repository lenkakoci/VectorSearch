"""Tests for the answering pipeline with the search and the model replaced.

The orchestration is what matters here: that the gate stops a question without
evidence before any model call, that what the model returns is checked rather
than believed, and that the trace records each step.
"""

from __future__ import annotations

import pytest

import answer_service
from answer_prompts import Conflict, GroundedAnswer, Statement
from answer_service import NO_EVIDENCE, AnswerUnavailable, answer
from citation_check import NUMBER_UNSUPPORTED, VERIFIED
from search_service import SearchResult


def _hit(number: int, grade: int, text: str) -> dict:
    return {
        "chunk_id": f"c{number}",
        "document_id": "doc-a",
        "chunk_index": number,
        "section": "5. Realizace > 5.1 Vrty",
        "content_kind": "prose",
        "page_from": 14,
        "page_to": None,
        "chunk_raw": text,
        "token_count": 120,
        "title": "ROUDNO – HG POSUDEK",
        "municipality": "Roudno",
        "report_type": "hydrogeologický průzkum",
        "report_date": "2016-03-23",
        "organization": "UNIGEO, a.s.",
        "rerank_grade": grade,
        "rerank_reason": "důvod",
        "candidate_rank": number,
    }


HITS = [
    _hit(1, 3, "Navrženo bylo cca 12 ks hlubokých vrtů o hloubce okolo 80 m."),
    _hit(2, 2, "Vrty budou situovány na parcele č. 9/1."),
    _hit(3, 1, "Obec Roudno leží v Nízkém Jeseníku."),
]


def _search(hits, passed=None):
    debug = {
        "fetch": 80,
        "vector_candidates": 80,
        "fts_any_candidates": 80,
        "tsquery": {"czech": "'vrt'"},
        "rerank": {"reranker": "gemini", "model": "m", "candidates": len(hits), "passed": passed if passed is not None else len(hits), "min_grade": 2, "calls": 2, "ms": 5000, "graded": len(hits), "cached": 0},
    }
    return {"rerank": SearchResult(query="q", mode="rerank", limit=40, fetch=80, hits=hits, debug=debug)}


@pytest.fixture
def settings():
    class Settings:
        answer_model = "gemini-test"

    return Settings()


def test_an_answer_is_checked_not_believed(monkeypatch, settings):
    monkeypatch.setattr(answer_service, "compare", lambda *args, **kwargs: _search(HITS))
    monkeypatch.setattr(
        answer_service,
        "call_model",
        lambda model, prompt: GroundedAnswer(
            status="answered",
            statements=[
                Statement(
                    text="Navrženo bylo cca 12 ks vrtů o hloubce okolo 80 m.",
                    source_ids=[1],
                    quotes=["cca 12 ks hlubokých vrtů o hloubce okolo 80 m"],
                ),
                Statement(text="Vrtů je 14.", source_ids=[1], quotes=["cca 12 ks hlubokých vrtů"]),
            ],
            missing=["průměr vrtů"],
            conflicts=[Conflict(topic="hloubka", source_ids=[1, 99], description="rozpor")],
        ),
    )

    result = answer(None, "Kolik vrtů se navrhuje?", settings=settings, use_neighbours=False)

    assert result.status == "partial"
    assert [statement["check"] for statement in result.statements] == [VERIFIED, NUMBER_UNSUPPORTED]
    assert result.missing == ["průměr vrtů"]
    assert result.conflicts[0]["source_ids"] == [1]
    assert result.trace["validation"]["verified"] == 1
    assert result.trace["generation"]["model_status"] == "answered"
    assert result.trace["context"]["chosen"] == 2
    assert [source["cited"] for source in result.sources] == [True, False]
    assert result.model == "gemini-test"


def test_the_gate_stops_a_question_without_evidence_before_the_model(monkeypatch, settings):
    below = [_hit(1, 1, "nesouvisí"), _hit(2, 0, "také nesouvisí")]
    monkeypatch.setattr(answer_service, "compare", lambda *args, **kwargs: _search(below, passed=0))

    def fail(model, prompt):
        raise AssertionError("the model must not be called")

    monkeypatch.setattr(answer_service, "call_model", fail)

    result = answer(None, "Jaký je radonový index v Jihlavě?", settings=settings, use_neighbours=False)

    assert result.status == NO_EVIDENCE
    assert result.statements == []
    assert [source["role"] for source in result.sources] == ["pod prahem", "pod prahem"]
    assert result.trace["gate"] == {"min_grade": 2, "candidates": 2, "passed": 0}
    assert "context" not in result.trace


def test_a_model_failure_becomes_answer_unavailable(monkeypatch, settings):
    monkeypatch.setattr(answer_service, "compare", lambda *args, **kwargs: _search(HITS))

    def broken(model, prompt):
        raise ValueError("Model returned unparsable output")

    monkeypatch.setattr(answer_service, "call_model", broken)

    with pytest.raises(AnswerUnavailable, match="unparsable"):
        answer(None, "Kolik vrtů?", settings=settings, use_neighbours=False)


def test_an_empty_question_is_rejected(settings):
    with pytest.raises(ValueError, match="Nothing to ask"):
        answer(None, "   ", settings=settings)
