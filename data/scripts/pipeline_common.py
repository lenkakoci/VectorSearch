"""Shared configuration and path helpers for the ingestion pipeline."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from manifest import PipelineConfig, chunk_params_hash
from markdown_normalizer import MARKDOWN_VERSION
from schemas import SCHEMA_VERSION

SCRIPTS_DIR = Path(__file__).parent
DATA_DIR = (SCRIPTS_DIR / "..").resolve()
PROCESSED_DIR = DATA_DIR / "processed"
MARKDOWN_DIR = PROCESSED_DIR / "markdown"
EXTRACTED_DIR = PROCESSED_DIR / "extracted"
CHUNKS_DIR = PROCESSED_DIR / "chunks"
MANIFEST_PATH = PROCESSED_DIR / "manifest.json"

SUPPORTED_SUFFIXES = {".pdf", ".md", ".markdown"}


def configure_logging() -> None:
    """Set up logging with our modules at LOG_LEVEL and third parties quiet.

    Also forces UTF-8 on the console streams: report text is Czech and a legacy
    Windows code page raises UnicodeEncodeError on characters it cannot map.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s - %(levelname)s - %(message)s")
    for noisy in ("google_genai", "google", "httpx", "httpcore", "markitdown", "pdfminer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@dataclass(frozen=True)
class Settings:
    """Resolved pipeline settings from the environment."""

    input_dir: Path
    extraction_model: str
    embedding_model: str
    embedding_dimensions: int
    embedding_batch_size: int
    chunk_max_tokens: int
    chunk_overlap_tokens: int
    chunk_min_tokens: int
    contextualize: bool

    def pipeline_config(self) -> PipelineConfig:
        """Return the parameter set whose change forces re-processing."""
        return PipelineConfig(
            markdown_version=MARKDOWN_VERSION,
            schema_version=SCHEMA_VERSION,
            extraction_model=self.extraction_model,
            embedding_model=self.embedding_model,
            embedding_dimensions=self.embedding_dimensions,
            chunk_params=chunk_params_hash(
                self.chunk_max_tokens,
                self.chunk_overlap_tokens,
                self.chunk_min_tokens,
                self.contextualize,
            ),
        )


def _truthy(value: str | None, default: bool) -> bool:
    """Parse a boolean environment variable."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    """Load `.env` and resolve pipeline settings."""
    load_dotenv()
    raw_input_dir = os.getenv("REPORTS_INPUT_DIR") or str(DATA_DIR / "PDFs")
    input_dir = Path(raw_input_dir)
    if not input_dir.is_absolute():
        input_dir = (SCRIPTS_DIR / raw_input_dir).resolve()

    return Settings(
        input_dir=input_dir,
        extraction_model=os.getenv("GEMINI_MODEL", "gemini-3.7-flash"),
        embedding_model=os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"),
        embedding_dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "1536")),
        embedding_batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "100")),
        chunk_max_tokens=int(os.getenv("CHUNK_MAX_TOKENS", "800")),
        chunk_overlap_tokens=int(os.getenv("CHUNK_OVERLAP_TOKENS", "100")),
        chunk_min_tokens=int(os.getenv("CHUNK_MIN_TOKENS", "150")),
        contextualize=_truthy(os.getenv("CONTEXTUALIZE_CHUNKS"), True),
    )


def load_connection_params() -> dict:
    """Load PostgreSQL connection parameters from the environment.

    Mirrors the helper used by configure_postgresql.py so every script connects
    the same way.
    """
    load_dotenv()
    params = {
        "host": os.getenv("PGHOST", "localhost"),
        "port": int(os.getenv("PGPORT", "5432")),
        "database": os.getenv("PGDATABASE", "geodb"),
        "user": os.getenv("PGUSER", "admin"),
        "password": os.getenv("PGPASSWORD"),
    }
    missing = [key for key, value in params.items() if not value]
    if missing:
        raise ValueError(f"Missing PostgreSQL connection parameters: {missing}")
    return params


def ensure_dirs() -> None:
    """Create the processed-output directories."""
    for directory in (MARKDOWN_DIR, EXTRACTED_DIR, CHUNKS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def discover_sources(settings: Settings, extra_dirs: list[Path] | None = None) -> list[Path]:
    """Return supported source files from the input directory."""
    directories = [settings.input_dir, *(extra_dirs or [])]
    found: list[Path] = []
    for directory in directories:
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                found.append(path)
    return found


def stage_outputs(key: str) -> dict[str, Path]:
    """Return the file each stage produces for a source key.

    ``import`` is absent on purpose - its result lives in the database, not on
    disk. Re-running ``chunk`` cascades into it anyway.
    """
    stem = Path(key).stem
    return {
        "markdown": MARKDOWN_DIR / f"{stem}.md",
        "extract": EXTRACTED_DIR / f"{stem}.json",
        "chunk": CHUNKS_DIR / f"{stem}.parquet",
    }


def resolve_sources(
    settings: Settings, items: list[str], extra_dirs: list[Path] | None = None
) -> list[Path]:
    """Resolve ``--only`` arguments to source files.

    Accepts a path, a file name, or the bare stem, so that the same argument
    works whichever script it is given to. The stage scripts key off the stem
    while the source scripts key off the file, and having to remember which
    wanted ``Roudno`` and which wanted ``Roudno.pdf`` was a trap.
    """
    available = discover_sources(settings, extra_dirs=extra_dirs)
    by_name = {path.name: path for path in available}
    by_stem = {path.stem: path for path in available}

    resolved: list[Path] = []
    for item in items:
        candidate = Path(item)
        if not candidate.exists():
            candidate = settings.input_dir / item
        if candidate.exists() and candidate.is_file():
            resolved.append(candidate)
            continue

        match = by_name.get(item) or by_stem.get(item) or by_stem.get(Path(item).stem)
        if match is None:
            raise FileNotFoundError(f"Source not found: {item}")
        resolved.append(match)
    return resolved


def source_key(path: Path) -> str:
    """Return the manifest key for a source file.

    Relative to the data directory when possible, so the manifest stays portable
    across machines.
    """
    try:
        return path.resolve().relative_to(DATA_DIR).as_posix()
    except ValueError:
        return path.resolve().as_posix()
