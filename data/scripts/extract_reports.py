"""Convert reports to Markdown and extract structured metadata with an LLM.

    PDF --MarkItDown--> processed/markdown/<stem>.md --LLM--> processed/extracted/<stem>.json

Unlike the reference project's ``process_pdfs.py`` (which only prints to the
console), this persists every intermediate result. That matters because the two
expensive operations have different lifetimes: Markdown conversion depends only
on the source file, while extraction depends on SCHEMA_VERSION and the model.
Bumping the schema re-extracts from cached Markdown without re-parsing any PDF.

Markdown files are accepted as input too, which covers both the test fixture and
re-extraction from cache.

Run from data/scripts:
    uv run python extract_reports.py                   # process new/changed files
    uv run python extract_reports.py --markdown-only    # convert only, no LLM calls
    uv run python extract_reports.py --force            # ignore the manifest
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import sys
import uuid
from pathlib import Path

from google import genai
from google.genai import types
from gemini_auth import create_gemini_client, is_retryable_error
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from manifest import Manifest, file_sha256, timestamp_key, utc_now
from pipeline_common import (
    DATA_DIR,
    EXTRACTED_DIR,
    MANIFEST_PATH,
    MARKDOWN_DIR,
    Settings,
    configure_logging,
    discover_sources,
    ensure_dirs,
    load_settings,
    source_key,
)
from schemas import EXTRACTION_INSTRUCTIONS, SCHEMA_VERSION, GeologicalReport

logger = logging.getLogger(__name__)

# Stable namespace so a given source file always maps to the same document UUID.
_DOCUMENT_NAMESPACE = uuid.UUID("6f9b1c2e-7a54-4c3b-9f0d-2a1e5b8c4d17")


def document_id_for(key: str) -> str:
    """Return a deterministic document UUID for a manifest key."""
    return str(uuid.uuid5(_DOCUMENT_NAMESPACE, key))


def build_client() -> tuple[genai.Client, str]:
    """Build a Gemini client and resolve the extraction model."""
    model = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
    return create_gemini_client(), model


def to_markdown(path: Path) -> str:
    """Convert a source file to Markdown.

    Markdown inputs pass through unchanged; PDFs go through MarkItDown.
    """
    if path.suffix.lower() in {".md", ".markdown"}:
        return path.read_text(encoding="utf-8")

    from markitdown import MarkItDown

    result = MarkItDown().convert(path)
    content = (
        getattr(result, "text_content", None)
        or getattr(result, "text", None)
        or getattr(result, "markdown", "")
    )
    return content or ""


def page_texts(path: Path) -> list[str]:
    """Return per-page text for a PDF, used for best-effort page attribution.

    Returns an empty list for non-PDF inputs or when extraction fails - page
    ranges are a nice-to-have, never a hard requirement.
    """
    if path.suffix.lower() != ".pdf":
        return []
    try:
        from pypdf import PdfReader

        return [(page.extract_text() or "") for page in PdfReader(str(path)).pages]
    except Exception as exc:  # noqa: BLE001 - page numbers are optional
        logger.warning("Could not build page map for %s: %s", path.name, exc)
        return []


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    retry=retry_if_exception(is_retryable_error),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def extract_metadata(client: genai.Client, model: str, markdown: str) -> dict:
    """Call Gemini for grounded structured extraction.

    ``response_schema`` binds the Pydantic model directly, so ``response.parsed``
    comes back as a validated ``GeologicalReport``.
    """
    response = client.models.generate_content(
        model=model,
        contents=(
            "Zde je uplny text geologickeho posudku prevedeny do Markdownu.\n"
            "Vytahni z nej metadata podle schematu.\n\n"
            "<dokument>\n"
            f"{markdown}\n"
            "</dokument>"
        ),
        config=types.GenerateContentConfig(
            system_instruction=EXTRACTION_INSTRUCTIONS,
            response_mime_type="application/json",
            response_schema=GeologicalReport,
            # Extraction must be reproducible, not creative.
            temperature=0.0,
        ),
    )
    parsed = response.parsed
    if not isinstance(parsed, GeologicalReport):
        raise RuntimeError(f"Gemini did not return a parsable GeologicalReport: {parsed!r}")
    return parsed.model_dump()


def process_one(
    path: Path,
    *,
    client: genai.Client | None,
    model: str,
    manifest: Manifest,
    markdown_only: bool,
    force: bool,
) -> bool:
    """Convert and extract a single report. Returns True when work was done."""
    key = source_key(path)
    sha = file_sha256(path)
    entry = manifest.get(key)

    markdown_path = MARKDOWN_DIR / f"{path.stem}.md"
    needs_markdown = force or entry.get("sha256") != sha or not markdown_path.exists()

    if needs_markdown:
        logger.info("Converting %s to Markdown", path.name)
        markdown = to_markdown(path)
        if not markdown.strip():
            logger.error("Empty Markdown extracted from %s; skipping", path.name)
            return False
        markdown_path.write_text(markdown, encoding="utf-8")
        pages = page_texts(path)
        if pages:
            _write_page_map(path.stem, pages)
        manifest.update(
            key,
            sha256=sha,
            source_path=path.resolve().as_posix(),
            markdown_path=markdown_path.relative_to(DATA_DIR).as_posix(),
            page_count=len(pages) or None,
            markdown_at=utc_now(),
        )
    else:
        markdown = markdown_path.read_text(encoding="utf-8")

    if markdown_only:
        return needs_markdown

    extracted_path = EXTRACTED_DIR / f"{path.stem}.json"
    needs_extract = (
        force
        or needs_markdown
        or not extracted_path.exists()
        or not entry.get(timestamp_key("extract"))
        or entry.get("extraction_schema_version") != SCHEMA_VERSION
        or entry.get("extraction_model") != model
    )
    if not needs_extract:
        logger.debug("Extraction up to date for %s", path.name)
        return False

    if client is None:
        raise RuntimeError("Gemini client required for extraction")

    logger.info(
        "Extracting metadata from %s (model=%s, schema=v%d)", path.name, model, SCHEMA_VERSION
    )
    metadata = extract_metadata(client, model, markdown)

    document_id = document_id_for(key)
    payload = {
        "document_id": document_id,
        "source_file": key,
        "source_sha256": sha,
        "markdown_path": markdown_path.relative_to(DATA_DIR).as_posix(),
        "extraction_schema_version": SCHEMA_VERSION,
        "extraction_model": model,
        "extracted_at": utc_now(),
        "extraction": metadata,
    }
    extracted_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest.update(
        key,
        document_id=document_id,
        extraction_schema_version=SCHEMA_VERSION,
        extraction_model=model,
        extracted_at=utc_now(),
    )

    missing = metadata.get("missing_fields") or []
    extra = [item["key"] for item in metadata.get("extra_fields") or []]
    logger.info(
        "  title=%r | missing=%d %s | extra=%s",
        (metadata.get("title") or "")[:60],
        len(missing),
        missing[:5],
        extra[:8],
    )
    return True


def _write_page_map(stem: str, pages: list[str]) -> None:
    """Persist per-page text so the chunker can attribute page ranges."""
    target = MARKDOWN_DIR / f"{stem}.pages.json"
    target.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Extract structured metadata from geological reports."
    )
    parser.add_argument(
        "--markdown-only", action="store_true", help="Convert to Markdown only, no LLM calls"
    )
    parser.add_argument(
        "--force", action="store_true", help="Reprocess even when the manifest says it is current"
    )
    parser.add_argument("--only", nargs="*", help="Process only these files (name or path)")
    parser.add_argument("--input-dir", help="Override the input directory")
    return parser.parse_args(argv)


def select_sources(settings: Settings, args: argparse.Namespace) -> list[Path]:
    """Resolve which source files to process."""
    if args.only:
        resolved: list[Path] = []
        for item in args.only:
            candidate = Path(item)
            if not candidate.exists():
                candidate = settings.input_dir / item
            if not candidate.exists():
                raise FileNotFoundError(f"Source not found: {item}")
            resolved.append(candidate)
        return resolved
    return discover_sources(settings, extra_dirs=[DATA_DIR / "samples"])


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    configure_logging()
    args = parse_args(argv if argv is not None else sys.argv[1:])
    settings = load_settings()
    if args.input_dir:
        settings = dataclasses.replace(settings, input_dir=Path(args.input_dir).resolve())

    ensure_dirs()
    manifest = Manifest(MANIFEST_PATH)

    sources = select_sources(settings, args)
    if not sources:
        logger.warning("No source files found in %s", settings.input_dir)
        return 0

    client: genai.Client | None = None
    model = settings.extraction_model
    if not args.markdown_only:
        client, model = build_client()

    processed = 0
    failed = 0
    for path in sources:
        try:
            if process_one(
                path,
                client=client,
                model=model,
                manifest=manifest,
                markdown_only=args.markdown_only,
                force=args.force,
            ):
                processed += 1
        except Exception as exc:  # noqa: BLE001 - one bad report must not stop the batch
            failed += 1
            logger.exception("Failed processing %s: %s", path.name, exc)
        finally:
            manifest.save()

    logger.info(
        "Extraction done: %d processed, %d failed, %d total", processed, failed, len(sources)
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
