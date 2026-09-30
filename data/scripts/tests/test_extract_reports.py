"""Tests for the decision to re-read a PDF, which is a decision about money.

pdfminer's layout analysis is not reproducible across processes, so parsing the
same report twice can return the same page with one stray glyph on the other
side of a blank line. The byte comparison in ``process_one`` reads that as a
changed document and charges a re-extraction and a re-embedding for it. Not
parsing twice is the fix, and these tests are what keep it in place.
"""

from __future__ import annotations

import json

import extract_reports


def _page_map(tmp_path, monkeypatch, payload: str | None) -> list[str]:
    """Point the module at ``tmp_path`` and write ``payload`` as the page map."""
    monkeypatch.setattr(extract_reports, "MARKDOWN_DIR", tmp_path)
    if payload is not None:
        (tmp_path / "report.pages.json").write_text(payload, encoding="utf-8")

    calls: list[str] = []

    def _never_free(path):
        calls.append(path.name)
        return ["freshly parsed"]

    monkeypatch.setattr(extract_reports, "pdf_pages", _never_free)
    return calls


def test_a_cached_page_map_is_used_and_the_pdf_is_not_touched(tmp_path, monkeypatch):
    """The whole point: a report already converted is never parsed again."""
    pages = ["strana jedna", "strana dvě"]
    calls = _page_map(tmp_path, monkeypatch, json.dumps(pages, ensure_ascii=False))

    result = extract_reports._pages_for(tmp_path / "report.pdf", force=False)

    assert result == pages
    assert calls == [], "pdfminer must not be called when a page map exists"


def test_a_missing_page_map_falls_back_to_parsing(tmp_path, monkeypatch):
    """A new report has no cache, and that is the only way one gets written."""
    calls = _page_map(tmp_path, monkeypatch, None)

    result = extract_reports._pages_for(tmp_path / "report.pdf", force=False)

    assert result == ["freshly parsed"]
    assert calls == ["report.pdf"]


def test_a_truncated_page_map_falls_back_to_parsing(tmp_path, monkeypatch):
    """A run killed mid-write leaves half a JSON file; that is not the text."""
    calls = _page_map(tmp_path, monkeypatch, '["strana jedna", "strana d')

    result = extract_reports._pages_for(tmp_path / "report.pdf", force=False)

    assert result == ["freshly parsed"]
    assert calls == ["report.pdf"]


def test_an_empty_page_map_falls_back_to_parsing(tmp_path, monkeypatch):
    """An empty list is not a page map, it is a conversion that produced nothing."""
    calls = _page_map(tmp_path, monkeypatch, "[]")

    result = extract_reports._pages_for(tmp_path / "report.pdf", force=False)

    assert result == ["freshly parsed"]
    assert calls == ["report.pdf"]


def test_force_parses_even_with_a_cached_page_map(tmp_path, monkeypatch):
    """--force is the escape hatch, so it may not be served from the cache."""
    calls = _page_map(tmp_path, monkeypatch, json.dumps(["strana jedna"]))

    result = extract_reports._pages_for(tmp_path / "report.pdf", force=True)

    assert result == ["freshly parsed"]
    assert calls == ["report.pdf"]


def test_the_recorded_digest_is_preferred_over_reading_the_file(tmp_path):
    """The digest is provenance, and a source report does not change under us."""
    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.4 whatever")

    assert extract_reports._source_sha(path, {"sha256": "abc123"}) == "abc123"


def test_a_missing_digest_is_computed(tmp_path):
    """An entry written before the digest was recorded still has to produce one."""
    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.4 whatever")

    for entry in ({}, {"sha256": None}, {"sha256": ""}):
        digest = extract_reports._source_sha(path, entry)
        assert len(digest) == 64, f"expected a sha256 hex digest for {entry!r}"
