"""Tests for the record of what people asked.

No API and no database: an answer is a stand-in object with the fields the
answering chain returns, and the file is written into a temporary directory.
"""

from __future__ import annotations

from types import SimpleNamespace

import answer_log


def _result() -> SimpleNamespace:
    return SimpleNamespace(
        question="Kolik vrtů se v Roudně navrhuje?",
        status="answered",
        model="gemini-test",
        prompt_version=2,
        statements=[
            {
                "text": "Navrženo je cca 12 ks vrtů.",
                "check": "verified",
                "note": "citát i čísla ověřeny ve zdroji",
                "source_ids": [1],
                "quotes": ["cca 12 ks hlubokých vrtů"],
            }
        ],
        missing=["průměr vrtů"],
        conflicts=[{"topic": "hloubka", "source_ids": [1], "description": "rozpor"}],
        sources=[
            {
                "id": 1,
                "cited": True,
                "role": "nalezeno",
                "document_id": "doc-a",
                "title": "ROUDNO – HG POSUDEK",
                "chunk_index": 38,
                "section": "5. Realizace",
                "page_from": 14,
                "content_kind": "prose",
                "rerank_grade": 3,
                "chunk_raw": "dlouhý text, který do logu nepatří",
            }
        ],
        trace={
            "gate": {"min_grade": 2, "candidates": 40, "passed": 4},
            "context": {"sources": 8, "tokens": 4704},
            "validation": {"statements": 1, "verified": 1},
            "total_ms": 13420.1,
            "prompt": "x" * 5000,
            "raw_answer": {"status": "answered"},
        },
    )


def test_the_record_keeps_what_a_golden_entry_needs():
    line = answer_log.record(_result(), source="cli", filters={"municipality": "Roudno"}, ms=14000.4)
    assert line["question"].startswith("Kolik vrtů")
    assert line["status"] == "answered"
    assert line["source"] == "cli"
    assert line["filters"] == {"municipality": "Roudno"}
    # The question, the document and a verbatim quote: that is a golden entry.
    assert line["statements"][0]["quotes"] == ["cca 12 ks hlubokých vrtů"]
    assert line["sources"][0]["document_id"] == "doc-a"
    assert line["sources"][0]["cited"] is True
    assert line["conflicts"] == 1
    assert line["server_ms"] == 13420.1
    assert line["cache"] == "miss"
    assert line["client_ms"] == 14000.4
    assert line["asked_at"].endswith("+00:00")


def test_an_answer_from_the_cache_is_marked_as_such():
    result = _result()
    result.trace["cache"] = "hit"
    assert answer_log.record(result, source="api")["cache"] == "hit"


def test_the_record_leaves_out_what_is_large_and_reproducible():
    line = answer_log.record(_result(), source="api")
    assert "prompt" not in line
    assert "raw_answer" not in line
    # The chunk text is in the database already; the log points at it.
    assert "chunk_raw" not in line["sources"][0]


def test_a_written_line_reads_back(tmp_path):
    written = answer_log.append(answer_log.record(_result(), source="api"), tmp_path)
    assert written == tmp_path / answer_log.LOG_NAME
    answer_log.append(answer_log.record(_result(), source="cli"), tmp_path)
    records = answer_log.read(tmp_path)
    assert [item["source"] for item in records] == ["api", "cli"]
    assert records[0]["question"].startswith("Kolik vrtů")


def test_a_truncated_last_line_does_not_stop_the_read(tmp_path):
    answer_log.append(answer_log.record(_result(), source="api"), tmp_path)
    with (tmp_path / answer_log.LOG_NAME).open("a", encoding="utf-8") as handle:
        handle.write('{"question": "nedopsan')
    assert len(answer_log.read(tmp_path)) == 1


def test_reading_a_log_that_does_not_exist_yet_is_empty(tmp_path):
    assert answer_log.read(tmp_path / "nic") == []


def test_a_failed_write_does_not_raise(tmp_path):
    # The log lives under something that is a file, so the directory cannot be
    # made. An answer must survive that: the answer is the product.
    blocked = tmp_path / "soubor"
    blocked.write_text("ne", encoding="utf-8")
    assert answer_log.append(answer_log.record(_result(), source="api"), blocked / "hloub") is None
