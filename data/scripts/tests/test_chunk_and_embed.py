"""Tests for serving an unchanged chunk from the previous run.

Re-chunking used to cost a full re-embedding whatever the reason for it. Six
documents were re-embedded in full because pdfminer moved a glyph, and 23 of
their 1715 chunks had actually changed. What must not happen is the opposite
mistake: serving a vector that was not this model's answer to this text.
"""

from __future__ import annotations

import pandas as pd
import pytest

import chunk_and_embed
from manifest import PipelineConfig, chunk_params_hash


class _Settings:
    """The two fields ``cached_embeddings`` reads, and nothing else."""

    embedding_model = "gemini-embedding-001"
    embedding_dimensions = 1536

    def pipeline_config(self) -> PipelineConfig:
        return PipelineConfig(
            markdown_version=7,
            schema_version=1,
            extraction_model="gemini-3.7-flash",
            embedding_model=self.embedding_model,
            embedding_dimensions=self.embedding_dimensions,
            chunk_params=chunk_params_hash(800, 100, 200, True, 4),
        )


def _entry(**overrides) -> dict:
    entry = {
        "embedding_model": _Settings.embedding_model,
        "embedding_dimensions": _Settings.embedding_dimensions,
    }
    entry.update(overrides)
    return entry


@pytest.fixture
def parquet(tmp_path, monkeypatch):
    """Write a parquet with two embedded chunks and one annex chunk without a vector."""
    monkeypatch.setattr(chunk_and_embed, "CHUNKS_DIR", tmp_path)
    frame = pd.DataFrame(
        {
            "chunk_text": ["hladina podzemní vody", "zatřídění zemin", "vrtný profil J1"],
            "embedding": [[0.1] * 4, [0.2] * 4, None],
        }
    )
    frame.to_parquet(tmp_path / "report.parquet", index=False)
    return tmp_path


def test_an_unchanged_chunk_is_served_from_the_previous_run(parquet):
    """The saving: text that has not changed does not go to the model again."""
    known = chunk_and_embed.cached_embeddings("report", _entry(), _Settings())

    assert known["hladina podzemní vody"] == [0.1] * 4
    assert known["zatřídění zemin"] == [0.2] * 4


def test_an_annex_chunk_contributes_nothing(parquet):
    """A form has no vector, and a missing vector is not a cache hit."""
    known = chunk_and_embed.cached_embeddings("report", _entry(), _Settings())

    assert "vrtný profil J1" not in known
    assert len(known) == 2


def test_a_changed_chunk_misses(parquet):
    """The key is the text, so a moved glyph costs exactly one embedding."""
    known = chunk_and_embed.cached_embeddings("report", _entry(), _Settings())

    assert known.get("hladina  podzemní vody") is None


def test_another_model_or_dimensionality_shares_nothing(parquet):
    """A vector from another model is not this model's answer to this text."""
    settings = _Settings()

    assert chunk_and_embed.cached_embeddings(
        "report", _entry(embedding_model="text-embedding-3-large"), settings
    ) == {}
    assert chunk_and_embed.cached_embeddings(
        "report", _entry(embedding_dimensions=3072), settings
    ) == {}
    assert chunk_and_embed.cached_embeddings("report", {}, settings) == {}


def test_a_document_never_chunked_before_shares_nothing(tmp_path, monkeypatch):
    """No parquet, no reuse - and no crash on the first run of a new report."""
    monkeypatch.setattr(chunk_and_embed, "CHUNKS_DIR", tmp_path)

    assert chunk_and_embed.cached_embeddings("report", _entry(), _Settings()) == {}


class _Generator:
    """Records what it was asked to embed and answers positionally."""

    def __init__(self):
        self.asked: list[str] = []

    def embed(self, texts):
        self.asked.extend(texts)
        return [[float(len(text))] * 4 for text in texts]


def _fake_document(monkeypatch, tmp_path, texts, kinds):
    """Make ``process_one`` see exactly these chunks without touching the disk."""
    from chunker import Chunk

    chunks = [
        Chunk(chunk_index=index, section="1. Úvod", text=text, token_count=10, body=text)
        for index, text in enumerate(texts)
    ]
    monkeypatch.setattr(chunk_and_embed, "CHUNKS_DIR", tmp_path)
    # The manifest records the parquet relative to the data directory.
    monkeypatch.setattr(chunk_and_embed, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        chunk_and_embed,
        "chunk_document",
        lambda stem, settings: ("doc-1", chunks, list(texts), [(1, 1)] * len(texts), kinds),
    )


def test_a_reused_vector_lands_on_its_own_chunk(tmp_path, monkeypatch, parquet):
    """A vector on the wrong row would quietly answer with the wrong document.

    The two halves are embedded in different orders - one from the map, one from
    the model - so this is the test that the indices did not drift.
    """
    from manifest import Manifest

    texts = ["hladina podzemní vody", "nový text", "zatřídění zemin", "vrtný profil J1"]
    kinds = ["prose", "prose", "prose", chunk_and_embed.ANNEX]
    _fake_document(monkeypatch, tmp_path, texts, kinds)

    manifest = Manifest(tmp_path / "manifest.json")
    manifest.update("report.pdf", **_entry())
    generator = _Generator()

    count = chunk_and_embed.process_one(
        "report",
        "report.pdf",
        settings=_Settings(),
        generator=generator,
        manifest=manifest,
        reuse=True,
    )

    assert count == 4
    assert generator.asked == ["nový text"], "only the chunk that changed"

    written = pd.read_parquet(tmp_path / "report.parquet")
    by_text = dict(zip(written["chunk_text"], written["embedding"]))
    assert list(by_text["hladina podzemní vody"]) == [0.1] * 4
    assert list(by_text["zatřídění zemin"]) == [0.2] * 4
    assert list(by_text["nový text"]) == [float(len("nový text"))] * 4
    assert by_text["vrtný profil J1"] is None, "an annex chunk stays without a vector"


def test_force_embeds_everything_again(tmp_path, monkeypatch, parquet):
    """--force distrusts what is on disk, so reuse has to be off."""
    from manifest import Manifest

    texts = ["hladina podzemní vody", "zatřídění zemin"]
    _fake_document(monkeypatch, tmp_path, texts, ["prose", "prose"])

    manifest = Manifest(tmp_path / "manifest.json")
    manifest.update("report.pdf", **_entry())
    generator = _Generator()

    chunk_and_embed.process_one(
        "report",
        "report.pdf",
        settings=_Settings(),
        generator=generator,
        manifest=manifest,
        reuse=False,
    )

    assert generator.asked == texts
