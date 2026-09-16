"""Tests for remembering an answer that was already paid for.

Everything here is files and hashing: no API, no database. What matters is that
the key changes whenever something that could change the answer changes, and
that a broken cache reads as a miss rather than as an error.
"""

from __future__ import annotations

import json

import answer_cache

BASE = {
    "filters": {"municipality": "Roudno"},
    "options": {"min_grade": 2, "max_sources": 8},
    "model": "gemini-test",
    "prompt_version": 2,
    "corpus": "1700000000-4096",
}


def _key(question: str = "Kolik vrtů se v Roudně navrhuje?", **changes) -> str:
    return answer_cache.key_of(question, **{**BASE, **changes})


def test_the_same_question_asked_twice_shares_a_key():
    assert _key() == _key()
    # Spacing and case are not part of the question.
    assert _key("kolik   vrtů se v roudně NAVRHUJE?") == _key()


def test_everything_that_could_change_the_answer_changes_the_key():
    assert _key("Jak hluboko je voda v Lednici?") != _key()
    assert _key(filters={}) != _key()
    assert _key(options={"min_grade": 3, "max_sources": 8}) != _key()
    assert _key(model="gemini-other") != _key()
    assert _key(prompt_version=3) != _key()
    # A re-ingested corpus must not serve answers about the old chunks.
    assert _key(corpus="1700009999-5000") != _key()


def test_an_answer_reads_back_the_way_it_was_stored(tmp_path):
    payload = {"question": "Kolik vrtů?", "status": "answered", "statements": [{"text": "Dvanáct."}]}
    written = answer_cache.store("klic", payload, tmp_path)
    assert written == tmp_path / answer_cache.CACHE_DIR_NAME / "klic.json"
    assert answer_cache.load("klic", tmp_path) == payload


def test_a_question_never_asked_before_is_a_miss(tmp_path):
    assert answer_cache.load("neexistuje", tmp_path) is None


def test_a_damaged_file_is_a_miss_not_a_crash(tmp_path):
    answer_cache.store("klic", {"question": "x"}, tmp_path)
    (tmp_path / answer_cache.CACHE_DIR_NAME / "klic.json").write_text("{tohle není json", encoding="utf-8")
    assert answer_cache.load("klic", tmp_path) is None


def test_a_failed_write_is_not_fatal(tmp_path):
    blocked = tmp_path / "soubor"
    blocked.write_text("ne", encoding="utf-8")
    assert answer_cache.store("klic", {"question": "x"}, blocked / "hloub") is None


def test_clearing_removes_what_was_stored(tmp_path):
    answer_cache.store("a", {"question": "a"}, tmp_path)
    answer_cache.store("b", {"question": "b"}, tmp_path)
    assert answer_cache.clear(tmp_path) == 2
    assert answer_cache.load("a", tmp_path) is None
    assert answer_cache.clear(tmp_path) == 0


def test_the_corpus_fingerprint_follows_the_manifest(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"documents": 16}), encoding="utf-8")
    first = answer_cache.corpus_fingerprint(manifest)
    assert first
    manifest.write_text(json.dumps({"documents": 17, "more": "data"}), encoding="utf-8")
    assert answer_cache.corpus_fingerprint(manifest) != first
    # Without a manifest there is nothing to fingerprint, and that is allowed.
    assert answer_cache.corpus_fingerprint(tmp_path / "nic.json") == ""
