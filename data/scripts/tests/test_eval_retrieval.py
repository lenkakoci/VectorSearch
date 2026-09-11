"""Tests for the golden-set evaluation that need no database and no API.

The repository's own golden set is loaded too, so a YAML mistake or a broken
rule fails here rather than halfway through a paid run.
"""

from __future__ import annotations

import pytest

from eval_retrieval import (
    GOLDEN_PATH,
    QUESTION_TYPES,
    Evidence,
    Question,
    evidence_ranks,
    first_rank,
    load_golden,
    recall_at,
    reciprocal_rank,
    select_questions,
    summarize,
)


def _write(tmp_path, text):
    path = tmp_path / "golden.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_repository_golden_set_is_valid():
    version, questions = load_golden(GOLDEN_PATH)
    assert version >= 1
    assert len(questions) >= 30
    assert len({question.id for question in questions}) == len(questions)
    assert sum(question.negative for question in questions) >= 5
    assert {question.type for question in questions} == set(QUESTION_TYPES)


def test_load_golden_reports_every_problem(tmp_path):
    path = _write(tmp_path, """
version: 1
questions:
  - id: a
    type: exact
    question: "První"
    evidence: [{doc: Roudno, contains: "12 ks"}]
  - id: a
    type: guess
    question: "Druhá"
    evidence: [{doc: Roudno, contains: "x"}]
  - id: b
    type: negative
    question: "Třetí"
    evidence: [{doc: Roudno, contains: "x"}]
  - id: c
    type: paraphrase
    question: ""
""")
    with pytest.raises(ValueError) as error:
        load_golden(path)
    message = str(error.value)
    assert "is already used" in message
    assert "unknown type 'guess'" in message
    assert "must not have evidence" in message
    assert "needs evidence" in message
    assert "question text is missing" in message


def test_contains_accepts_one_snippet_or_several(tmp_path):
    path = _write(tmp_path, """
questions:
  - id: one
    type: exact
    question: "q"
    evidence: [{doc: Roudno, contains: "12 ks"}]
  - id: many
    type: exact
    question: "q"
    evidence: [{doc: Roudno, contains: ["12 ks", "80 m"]}]
""")
    _, questions = load_golden(path)
    assert questions[0].evidence[0].contains == ("12 ks",)
    assert questions[1].evidence[0].contains == ("12 ks", "80 m")


def test_evidence_matches_document_and_normalised_text():
    item = Evidence(doc="průzkum-Lednice", contains=("v rozmezí od 0,4 – 1,0 m",))
    text = "Hladina  podzemní  vody  ustálená  se  vyskytovala  v rozmezí  od  0,4  –  1,0  m"
    assert item.matches("průzkum-Lednice", text)
    assert not item.matches("Roudno", text)
    assert not item.matches("průzkum-Lednice", "v rozmezí od 0,5 – 1,0 m")


HITS = [
    {"document_id": "d-roudno", "chunk_raw": "úvod bez odpovědi"},
    {"document_id": "d-lednice", "chunk_raw": "ustálená hladina 0,4 – 1,0 m pod povrchem"},
    {"document_id": "d-roudno", "chunk_raw": "hladina zastižena v úrovni 0,5 m p. t."},
]
STEMS = {"d-roudno": "Roudno", "d-lednice": "průzkum-Lednice"}


def test_evidence_ranks_find_the_first_matching_hit():
    question = Question(
        id="q",
        type="multi",
        question="?",
        evidence=(
            Evidence("průzkum-Lednice", ("0,4-1,0 m",)),
            Evidence("Roudno", ("0,5 m p. t.",)),
            Evidence("Zábřeh na Moravě", ("4,0 m p. t.",)),
        ),
    )
    assert evidence_ranks(HITS, question, STEMS) == [2, 3, None]


def test_metrics_over_evidence_ranks():
    ranks = [2, 3, None]
    assert first_rank(ranks) == 2
    assert reciprocal_rank(ranks) == 0.5
    assert recall_at(ranks, 1) == 0.0
    assert recall_at(ranks, 2) == pytest.approx(1 / 3)
    assert recall_at(ranks, 5) == pytest.approx(2 / 3)
    assert first_rank([None]) is None
    assert reciprocal_rank([None]) == 0.0


def test_summarize_averages_questions_with_an_answer_only():
    rows = [
        {"id": "a", "type": "exact", "negative": False, "modes": {"fts": {"ranks": [1]}}},
        {"id": "b", "type": "paraphrase", "negative": False, "modes": {"fts": {"ranks": [None]}}},
        {"id": "n", "type": "negative", "negative": True, "modes": {"fts": {"ranks": []}}},
    ]
    summary = summarize(rows, ("fts",), (5,))
    assert summary["all"]["fts"]["questions"] == 2
    assert summary["all"]["fts"]["mrr"] == 0.5
    assert summary["all"]["fts"]["recall@5"] == 0.5
    assert summary["all"]["fts"]["missed"] == 1
    assert summary["exact"]["fts"]["mrr"] == 1.0
    assert "negative" not in summary


def test_select_questions_by_id_and_type():
    questions = [
        Question("a", "exact", "?", (Evidence("Roudno", ("x",)),)),
        Question("b", "negative", "?", ()),
    ]
    assert [q.id for q in select_questions(questions, ["b"], None)] == ["b"]
    assert [q.id for q in select_questions(questions, None, ["exact"])] == ["a"]
    with pytest.raises(ValueError, match="Unknown question ids: zz"):
        select_questions(questions, ["zz"], None)
