"""Chunk report Markdown and generate embeddings.

    processed/markdown/<stem>.md + processed/extracted/<stem>.json
        --> processed/chunks/<stem>.parquet

Retry/backoff and batching follow the reference project's
``embeddings_simple_products.py``: tenacity with exponential wait on rate limits
and transient server errors, batches of 100.

Embeddings come from Gemini via the native ``google-genai`` SDK, using
``task_type=RETRIEVAL_DOCUMENT`` so the corpus side of the retrieval pair is
encoded correctly; ``search_reports.py`` uses RETRIEVAL_QUERY for the other side.

Two deliberate differences from the reference project:

- Parquet is written per document, not as one global file. A new report then
  costs one new file instead of regenerating the whole cache.
- Contextual Retrieval (Anthropic) is applied without any extra LLM call: the
  context prefix is assembled from metadata already extracted in the previous
  stage. A chunk saying "the water table was encountered at 3.2 m" is
  indistinguishable across hundreds of reports without it.

Run from data/scripts:
    uv run python chunk_and_embed.py
    uv run python chunk_and_embed.py --force
    uv run python chunk_and_embed.py --dry-run   # chunk only, no embedding calls
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
from google import genai
from google.genai import types
from gemini_auth import create_gemini_client, is_retryable_error, normalize
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from chunker import Chunk, chunk_markdown, count_tokens
from manifest import Manifest, timestamp_key, utc_now
from pipeline_common import (
    CHUNKS_DIR,
    DATA_DIR,
    EXTRACTED_DIR,
    MANIFEST_PATH,
    MARKDOWN_DIR,
    Settings,
    configure_logging,
    ensure_dirs,
    load_settings,
)

logger = logging.getLogger(__name__)

# Stable namespace so a chunk keeps its UUID across re-runs with equal parameters.
_CHUNK_NAMESPACE = uuid.UUID("2d4a7f61-93b8-4e05-8c7a-1f6d0b39e254")

# gemini-embedding-001 accepts about 2048 input tokens. tiktoken undercounts
# Czech relative to Gemini, so warn well below the limit rather than at it.
_INPUT_TOKEN_LIMIT = 2048
_INPUT_TOKEN_WARN = 1500

PARQUET_COLUMNS = [
    "document_id",
    "chunk_id",
    "chunk_index",
    "section",
    "page_from",
    "page_to",
    "chunk_raw",
    "chunk_text",
    "token_count",
    "embedding",
]


class EmbeddingsGenerator:
    """Batch embedding generation with retries and progress logging."""

    def __init__(self, *, model: str, dimensions: int, batch_size: int):
        """Build a Gemini client for embeddings."""
        self.client: genai.Client = create_gemini_client()
        self.model = model
        self.dimensions = dimensions
        self.batch_size = max(1, batch_size)
        logger.info(
            "Embeddings client ready (model=%s, dims=%d, task=RETRIEVAL_DOCUMENT)",
            self.model,
            self.dimensions,
        )

    @retry(
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=1, min=2, max=90),
        retry=retry_if_exception(is_retryable_error),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed one batch of chunk texts.

        ``task_type=RETRIEVAL_DOCUMENT`` tells Gemini these are corpus documents
        rather than queries; the query side uses RETRIEVAL_QUERY. Matching the
        pair meaningfully improves retrieval quality and has no OpenAI analogue.

        ``auto_truncate`` is deliberately not set: the Developer API (API key)
        rejects it as a Vertex-only parameter. Oversized input therefore surfaces
        as an API error, which is the behaviour we wanted anyway - a silently
        truncated chunk would quietly degrade recall. ``embed()`` warns before
        the call when a text looks close to the model's input limit.
        """
        response = self.client.models.embed_content(
            model=self.model,
            contents=list(texts),
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=self.dimensions,
            ),
        )
        return [normalize(item.values) for item in response.embeddings]

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed all texts in batches, warning about ones near the input limit."""
        for index, text in enumerate(texts):
            tokens = count_tokens(text)
            if tokens > _INPUT_TOKEN_WARN:
                logger.warning(
                    "Chunk %d is %d tokens (local estimate); %s accepts about %d. "
                    "Lower CHUNK_MAX_TOKENS if the request fails.",
                    index,
                    tokens,
                    self.model,
                    _INPUT_TOKEN_LIMIT,
                )

        vectors: list[list[float]] = []
        total = len(texts)
        for start in range(0, total, self.batch_size):
            batch = texts[start : start + self.batch_size]
            vectors.extend(self._embed_batch(batch))
            logger.info("  embedded %d/%d chunks", min(start + len(batch), total), total)
        return vectors


def build_context_prefix(extraction: dict[str, Any]) -> str:
    """Assemble the Contextual Retrieval prefix from already-extracted metadata.

    Costs no LLM call: everything here came out of the extraction stage.
    """
    parts = [
        value
        for value in (
            extraction.get("title"),
            extraction.get("locality"),
            extraction.get("report_type"),
        )
        if value
    ]
    header = ", ".join(parts)
    summary = (extraction.get("summary") or "").strip()
    if header and summary:
        return f"KONTEXT: {header}. {summary}"
    if header:
        return f"KONTEXT: {header}."
    return f"KONTEXT: {summary}" if summary else ""


def locate_pages(chunk_text: str, pages: list[str]) -> tuple[int | None, int | None]:
    """Best-effort page attribution by matching a chunk's opening text.

    Page numbers are optional metadata; returns (None, None) when unresolved.
    """
    if not pages:
        return (None, None)

    probe = " ".join(chunk_text.split())[:60]
    if not probe:
        return (None, None)

    normalised = [" ".join(page.split()) for page in pages]
    start_page: int | None = None
    for index, page in enumerate(normalised, start=1):
        if probe in page:
            start_page = index
            break
    if start_page is None:
        return (None, None)

    tail = " ".join(chunk_text.split())[-60:]
    for index in range(start_page - 1, len(normalised)):
        if tail in normalised[index]:
            return (start_page, index + 1)
    return (start_page, start_page)


def chunk_document(
    stem: str,
    settings: Settings,
) -> tuple[str, list[Chunk], list[str], list[tuple[int | None, int | None]]]:
    """Chunk one document and build the texts that will be embedded.

    Returns (document_id, chunks, embed_texts, page_ranges).
    """
    extracted_path = EXTRACTED_DIR / f"{stem}.json"
    markdown_path = MARKDOWN_DIR / f"{stem}.md"
    if not extracted_path.exists():
        raise FileNotFoundError(f"Missing extraction for {stem}; run extract_reports.py first")
    if not markdown_path.exists():
        raise FileNotFoundError(f"Missing Markdown for {stem}; run extract_reports.py first")

    payload = json.loads(extracted_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")

    chunks = chunk_markdown(
        markdown,
        max_tokens=settings.chunk_max_tokens,
        overlap=settings.chunk_overlap_tokens,
        min_tokens=settings.chunk_min_tokens,
    )

    prefix = build_context_prefix(payload.get("extraction", {})) if settings.contextualize else ""
    embed_texts = [f"{prefix}\n\n{chunk.text}" if prefix else chunk.text for chunk in chunks]

    pages_path = MARKDOWN_DIR / f"{stem}.pages.json"
    pages: list[str] = []
    if pages_path.exists():
        pages = json.loads(pages_path.read_text(encoding="utf-8"))
    page_ranges = [locate_pages(chunk.text, pages) for chunk in chunks]

    return payload["document_id"], chunks, embed_texts, page_ranges


def process_one(
    stem: str,
    key: str,
    *,
    settings: Settings,
    generator: EmbeddingsGenerator | None,
    manifest: Manifest,
) -> int:
    """Chunk, embed and cache one document. Returns the chunk count."""
    document_id, chunks, embed_texts, page_ranges = chunk_document(stem, settings)
    if not chunks:
        logger.warning("No chunks produced for %s", stem)
        return 0

    logger.info(
        "%s: %d chunks (%d-%d tokens)",
        stem,
        len(chunks),
        min(chunk.token_count for chunk in chunks),
        max(chunk.token_count for chunk in chunks),
    )

    if generator is None:
        for chunk in chunks:
            logger.info("  [%02d] %-40s %4d tok", chunk.chunk_index, (chunk.section or "-")[:40], chunk.token_count)
        return len(chunks)

    vectors = generator.embed(embed_texts)

    rows = [
        {
            "document_id": document_id,
            "chunk_id": str(uuid.uuid5(_CHUNK_NAMESPACE, f"{document_id}:{chunk.chunk_index}")),
            "chunk_index": chunk.chunk_index,
            "section": chunk.section,
            "page_from": page_range[0],
            "page_to": page_range[1],
            "chunk_raw": chunk.text,
            "chunk_text": embed_text,
            "token_count": chunk.token_count,
            "embedding": vector,
        }
        for chunk, embed_text, vector, page_range in zip(chunks, embed_texts, vectors, page_ranges)
    ]

    frame = pd.DataFrame(rows, columns=PARQUET_COLUMNS)
    output_path = CHUNKS_DIR / f"{stem}.parquet"
    frame.to_parquet(output_path, index=False)
    logger.info("Saved %d chunks to %s", len(frame), output_path.name)

    config = settings.pipeline_config()
    manifest.update(
        key,
        chunk_count=len(frame),
        chunk_params_hash=config.chunk_params,
        embedding_model=settings.embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
        chunks_path=output_path.relative_to(DATA_DIR).as_posix(),
        chunked_at=utc_now(),
    )
    return len(frame)


def needs_chunking(entry: dict[str, Any], settings: Settings, stem: str, force: bool) -> bool:
    """Decide whether a document must be re-chunked."""
    if force:
        return True
    if not entry.get(timestamp_key("chunk")):
        return True
    if not (CHUNKS_DIR / f"{stem}.parquet").exists():
        return True
    config = settings.pipeline_config()
    return (
        entry.get("chunk_params_hash") != config.chunk_params
        or entry.get("embedding_model") != config.embedding_model
        or entry.get("embedding_dimensions") != config.embedding_dimensions
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Chunk and embed extracted geological reports.")
    parser.add_argument("--force", action="store_true", help="Re-chunk and re-embed everything")
    parser.add_argument(
        "--dry-run", action="store_true", help="Chunk and print the plan without calling the API"
    )
    parser.add_argument("--only", nargs="*", help="Restrict to these documents (stem, file name or path)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    configure_logging()
    args = parse_args(argv if argv is not None else sys.argv[1:])
    settings = load_settings()
    ensure_dirs()
    manifest = Manifest(MANIFEST_PATH)

    # Match on the stem so that Roudno, Roudno.pdf and PDFs/Roudno.pdf all work -
    # the source scripts take a file, this one takes a stem, and having to
    # remember which is which was a trap.
    wanted = {Path(item).stem for item in args.only} if args.only else None

    targets: list[tuple[str, str]] = []
    not_extracted = 0
    for key in manifest.keys():
        stem = Path(key).stem
        if wanted is not None and stem not in wanted:
            continue
        entry = manifest.get(key)
        if not entry.get(timestamp_key("extract")):
            logger.debug("Skipping %s: not extracted yet", stem)
            not_extracted += 1
            continue
        if needs_chunking(entry, settings, stem, args.force) or args.dry_run:
            targets.append((stem, key))

    if not targets:
        if not_extracted:
            logger.info(
                "Nothing to chunk: %d document(s) not extracted yet. Run extract_reports.py first.",
                not_extracted,
            )
        else:
            logger.info("Nothing to chunk; all documents are up to date")
        return 0

    generator: EmbeddingsGenerator | None = None
    if not args.dry_run:
        generator = EmbeddingsGenerator(
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            batch_size=settings.embedding_batch_size,
        )

    total_chunks = 0
    failed = 0
    for stem, key in targets:
        try:
            total_chunks += process_one(
                stem, key, settings=settings, generator=generator, manifest=manifest
            )
        except Exception as exc:  # noqa: BLE001 - one bad document must not stop the batch
            failed += 1
            logger.exception("Failed chunking %s: %s", stem, exc)
        finally:
            if not args.dry_run:
                manifest.save()

    logger.info(
        "Chunking done: %d documents, %d chunks, %d failed", len(targets) - failed, total_chunks, failed
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
