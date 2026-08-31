"""Pipeline state tracking for incremental processing.

The manifest records, per source file, what has already been done and under
which parameters. ``ingest.py`` diffs the manifest against the current
configuration to decide which stages need to re-run:

    source sha256 changed        -> everything, starting from PDF -> Markdown
    MARKDOWN_VERSION             -> markdown -> extract -> chunk -> embed -> import
    SCHEMA_VERSION or LLM model  -> extract -> chunk -> embed -> import
    chunk params or embed model  -> chunk -> embed -> import
    nothing changed              -> skip the file

This is what makes "run it again whenever a new report arrives" cheap: a new
report costs one extraction, and bumping SCHEMA_VERSION re-extracts everything
from cached Markdown without re-parsing a single PDF.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"

# Pipeline stages in dependency order. Invalidating a stage invalidates all later ones.
STAGES = ("markdown", "extract", "chunk", "import")


def utc_now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def file_sha256(path: Path) -> str:
    """Return the SHA-256 hex digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def chunk_params_hash(max_tokens: int, overlap: int, min_tokens: int, contextualize: bool) -> str:
    """Return a short stable hash of the chunker configuration.

    Any change here invalidates chunking and everything downstream.
    """
    payload = f"{max_tokens}|{overlap}|{min_tokens}|{int(contextualize)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class PipelineConfig:
    """Parameters whose change forces re-processing."""

    markdown_version: int
    schema_version: int
    extraction_model: str
    embedding_model: str
    embedding_dimensions: int
    chunk_params: str


class Manifest:
    """Read/write access to the pipeline state file."""

    def __init__(self, path: Path):
        """Load the manifest from ``path``, starting empty when absent."""
        self.path = path
        self._entries: dict[str, dict[str, Any]] = {}
        if path.exists():
            try:
                self._entries = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.warning("Manifest at %s is corrupt; starting from scratch", path)
                self._entries = {}

    def get(self, key: str) -> dict[str, Any]:
        """Return the entry for ``key``, or an empty dict."""
        return self._entries.get(key, {})

    def update(self, key: str, **fields: Any) -> None:
        """Merge ``fields`` into the entry for ``key``."""
        entry = self._entries.setdefault(key, {})
        entry.update(fields)

    def keys(self) -> list[str]:
        """Return all tracked source keys."""
        return sorted(self._entries)

    def save(self) -> None:
        """Write the manifest to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._entries, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def stages_to_run(
        self,
        key: str,
        sha256: str,
        config: PipelineConfig,
        outputs: dict[str, Path] | None = None,
    ) -> set[str]:
        """Return the set of stages that must run for ``key``.

        Stages cascade: invalidating an early stage invalidates all later ones.

        ``outputs`` maps a stage to the file it produces. A stage whose file is
        gone counts as stale however recent its timestamp: ``processed/`` is a
        cache and deleting part of it to force a rebuild is a reasonable thing to
        do, but the timestamps alone cannot see that and would report the work as
        already done.
        """
        entry = self.get(key)
        if not entry:
            return set(STAGES)

        if entry.get("sha256") != sha256:
            return set(STAGES)

        stale_from: int | None = None

        if entry.get("markdown_version") != config.markdown_version:
            stale_from = STAGES.index("markdown")
        elif (
            entry.get("extraction_schema_version") != config.schema_version
            or entry.get("extraction_model") != config.extraction_model
        ):
            stale_from = STAGES.index("extract")
        elif (
            entry.get("chunk_params_hash") != config.chunk_params
            or entry.get("embedding_model") != config.embedding_model
            or entry.get("embedding_dimensions") != config.embedding_dimensions
        ):
            stale_from = STAGES.index("chunk")

        pending = set()
        for index, stage in enumerate(STAGES):
            done = entry.get(_timestamp_key(stage))
            output = (outputs or {}).get(stage)
            missing = output is not None and not output.exists()
            if not done or missing or (stale_from is not None and index >= stale_from):
                pending.add(stage)

        # Cascade: once a stage runs, everything after it must run too.
        if pending:
            first = min(STAGES.index(stage) for stage in pending)
            pending = set(STAGES[first:])
        return pending


def _timestamp_key(stage: str) -> str:
    """Return the manifest field name holding a stage's completion time."""
    return {
        "markdown": "markdown_at",
        "extract": "extracted_at",
        "chunk": "chunked_at",
        "import": "imported_at",
    }[stage]


def timestamp_key(stage: str) -> str:
    """Public alias of the stage timestamp field name."""
    return _timestamp_key(stage)
