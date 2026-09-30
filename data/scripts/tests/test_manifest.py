"""Tests for the invalidation logic - the one thing standing between a change
and a paid re-run of the corpus.

``stages_to_run`` decides what a run costs, and it no longer watches the source
file. These tests fix both halves of that: what it must still react to, and the
one thing it deliberately ignores.
"""

from __future__ import annotations

from manifest import STAGES, Manifest, PipelineConfig, chunk_params_hash

CONFIG = PipelineConfig(
    markdown_version=7,
    schema_version=1,
    extraction_model="gemini-3.7-flash",
    embedding_model="gemini-embedding-001",
    embedding_dimensions=1536,
    chunk_params=chunk_params_hash(800, 100, 200, True, 4),
)


def _current_entry() -> dict:
    """Return an entry that matches CONFIG in every respect and is fully done."""
    return {
        "sha256": "recorded-digest",
        "markdown_version": CONFIG.markdown_version,
        "extraction_schema_version": CONFIG.schema_version,
        "extraction_model": CONFIG.extraction_model,
        "chunk_params_hash": CONFIG.chunk_params,
        "embedding_model": CONFIG.embedding_model,
        "embedding_dimensions": CONFIG.embedding_dimensions,
        "markdown_at": "2026-09-30T08:00:00+00:00",
        "extracted_at": "2026-09-30T08:01:00+00:00",
        "chunked_at": "2026-09-30T08:02:00+00:00",
        "imported_at": "2026-09-30T08:03:00+00:00",
    }


def _manifest(tmp_path, entry: dict) -> Manifest:
    manifest = Manifest(tmp_path / "manifest.json")
    manifest.update("report.pdf", **entry)
    return manifest


def test_nothing_to_do_when_every_version_matches(tmp_path):
    """The row that makes an incremental pipeline worth having."""
    manifest = _manifest(tmp_path, _current_entry())

    assert manifest.stages_to_run("report.pdf", CONFIG) == set()


def test_an_unknown_source_runs_every_stage(tmp_path):
    """A new report costs one extraction, and that starts here."""
    manifest = Manifest(tmp_path / "manifest.json")

    assert manifest.stages_to_run("report.pdf", CONFIG) == set(STAGES)


def test_the_source_digest_is_not_watched(tmp_path):
    """A submitted survey does not change, so its digest cannot invalidate.

    Watching it meant reading every byte of every PDF on every run to confirm
    what the manifest already said.
    """
    entry = _current_entry()
    entry["sha256"] = "something else entirely"
    manifest = _manifest(tmp_path, entry)

    assert manifest.stages_to_run("report.pdf", CONFIG) == set()


def test_each_version_invalidates_its_own_stage_and_everything_after(tmp_path):
    """The cascade is the promise: equal versions mean equal output."""
    cases = {
        "markdown_version": {"markdown", "extract", "chunk", "import"},
        "extraction_schema_version": {"extract", "chunk", "import"},
        "extraction_model": {"extract", "chunk", "import"},
        "chunk_params_hash": {"chunk", "import"},
        "embedding_model": {"chunk", "import"},
        "embedding_dimensions": {"chunk", "import"},
    }
    for field, expected in cases.items():
        entry = _current_entry()
        entry[field] = 999 if isinstance(entry[field], int) else "stale"
        manifest = _manifest(tmp_path, entry)

        assert manifest.stages_to_run("report.pdf", CONFIG) == expected, field


def test_a_missing_output_file_is_stale_however_recent_its_timestamp(tmp_path):
    """processed/ is a cache, and deleting part of it is how a rebuild is asked for."""
    manifest = _manifest(tmp_path, _current_entry())
    gone = tmp_path / "never-written.parquet"

    pending = manifest.stages_to_run("report.pdf", CONFIG, outputs={"chunk": gone})

    assert pending == {"chunk", "import"}
