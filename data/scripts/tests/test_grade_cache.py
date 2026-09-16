"""Tests for keeping grades between processes.

Files and hashing only. The point of the key is that a grade never outlives
the text it was given for: a chunk id survives re-chunking, so the corpus
fingerprint has to be part of it.
"""

from __future__ import annotations

import json

import grade_cache
import rerank_service
from rerank_service import GeminiGrader

GRADES = {"chunk-a": (3, "obsahuje údaj"), "chunk-b": (0, "nesouvisí")}


def test_the_same_question_finds_its_grades(tmp_path):
    key = grade_cache.key_of("gemini-test", "Kolik vrtů?", corpus="1-2")
    grade_cache.store(key, GRADES, tmp_path, model="gemini-test", query="Kolik vrtů?")
    assert grade_cache.load(key, tmp_path) == GRADES
    # Spacing and case are not part of the question.
    assert grade_cache.key_of("gemini-test", "kolik   VRTŮ?", corpus="1-2") == key


def test_a_new_corpus_or_model_does_not_reuse_old_grades():
    key = grade_cache.key_of("gemini-test", "Kolik vrtů?", corpus="1-2")
    assert grade_cache.key_of("gemini-test", "Kolik vrtů?", corpus="9-9") != key
    assert grade_cache.key_of("gemini-other", "Kolik vrtů?", corpus="1-2") != key


def test_nothing_stored_is_no_grades(tmp_path):
    assert grade_cache.load("neexistuje", tmp_path) == {}


def test_a_damaged_file_is_no_grades(tmp_path):
    key = grade_cache.key_of("m", "q", corpus="1")
    grade_cache.store(key, GRADES, tmp_path)
    (tmp_path / grade_cache.GRADES_DIR_NAME / f"{key}.json").write_text("{rozbité", encoding="utf-8")
    assert grade_cache.load(key, tmp_path) == {}


def test_a_grade_of_the_wrong_shape_is_skipped(tmp_path):
    key = grade_cache.key_of("m", "q", corpus="1")
    path = grade_cache.grades_dir(tmp_path)
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{key}.json").write_text(
        json.dumps({"grades": {"a": [3, "dobrý"], "b": "tohle není dvojice"}}), encoding="utf-8"
    )
    assert grade_cache.load(key, tmp_path) == {"a": (3, "dobrý")}


def test_clearing_removes_the_files(tmp_path):
    grade_cache.store(grade_cache.key_of("m", "q1", corpus="1"), GRADES, tmp_path)
    grade_cache.store(grade_cache.key_of("m", "q2", corpus="1"), GRADES, tmp_path)
    assert grade_cache.clear(tmp_path) == 2
    assert grade_cache.clear(tmp_path) == 0


def test_a_second_process_grades_nothing_it_already_paid_for(monkeypatch, tmp_path):
    """The disk layer is what the CLI and an evaluation run live on."""
    hits = [
        {"chunk_id": "chunk-a", "chunk_raw": "Navrženo je 12 vrtů.", "title": "Roudno"},
        {"chunk_id": "chunk-b", "chunk_raw": "Obec leží v Jeseníku.", "title": "Roudno"},
    ]
    calls: list[int] = []

    def fake_call(model, prompt):
        calls.append(len(prompt))
        return [
            rerank_service.ChunkGrade(id=1, grade=3, reason="obsahuje údaj"),
            rerank_service.ChunkGrade(id=2, grade=0, reason="nesouvisí"),
        ]

    monkeypatch.setattr(rerank_service, "call_grader", fake_call)
    monkeypatch.setattr(grade_cache, "corpus_fingerprint", lambda *args, **kwargs: "stálý-korpus")

    grader = GeminiGrader(model="gemini-test", cache_dir=tmp_path)
    first, stats = grader.grade("Kolik vrtů?", hits)
    assert stats["graded"] == 2 and stats["from_disk"] == 0
    assert [grade for grade, _ in first] == [3, 0]

    # A fresh process: the in-memory cache is gone, the file is not.
    rerank_service.cache_clear()
    second, stats = grader.grade("Kolik vrtů?", hits)
    assert len(calls) == 1, "model se volal podruhé, přestože známky byly na disku"
    assert stats["graded"] == 0 and stats["from_disk"] == 2
    assert [grade for grade, _ in second] == [3, 0]


def test_without_a_directory_nothing_is_written(monkeypatch, tmp_path):
    """A grader with no cache directory must not touch the disk at all."""
    monkeypatch.setattr(
        rerank_service,
        "call_grader",
        lambda model, prompt: [rerank_service.ChunkGrade(id=1, grade=2, reason="část odpovědi")],
    )
    grader = GeminiGrader(model="gemini-test")
    grader.grade("Kolik vrtů?", [{"chunk_id": "chunk-a", "chunk_raw": "text", "title": "t"}])
    assert list(tmp_path.iterdir()) == []
