"""Import extracted metadata and embedded chunks into PostgreSQL.

    processed/extracted/<stem>.json  --> documents
    processed/chunks/<stem>.parquet  --> document_chunks

The reference project's import scripts TRUNCATE before loading, because their
data is generated and disposable. Reports are real and accumulate, so this uses
``INSERT ... ON CONFLICT DO UPDATE`` instead - the pattern from
``import_concept_embeddings.py``.

Chunks are replaced per document rather than upserted: the chunk count changes
between runs when chunk parameters change, and upserting by ``chunk_index``
would leave orphans behind. The delete and the insert share one transaction.

Run from data/scripts:
    uv run python import_reports.py
    uv run python import_reports.py --force
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2

from manifest import Manifest, timestamp_key, utc_now
from pipeline_common import (
    CHUNKS_DIR,
    EXTRACTED_DIR,
    MANIFEST_PATH,
    configure_logging,
    load_connection_params,
)

logger = logging.getLogger(__name__)

_INSERT_DOCUMENT = """
INSERT INTO public.documents (
    id, source_file, source_sha256, markdown_path,
    title, report_type, locality, report_date, author, client, summary,
    extraction_json, extraction_schema_version, extraction_model, updated_at
) VALUES (
    %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s,
    %s::jsonb, %s, %s, now()
)
ON CONFLICT (source_file) DO UPDATE SET
    id = EXCLUDED.id,
    source_sha256 = EXCLUDED.source_sha256,
    markdown_path = EXCLUDED.markdown_path,
    title = EXCLUDED.title,
    report_type = EXCLUDED.report_type,
    locality = EXCLUDED.locality,
    report_date = EXCLUDED.report_date,
    author = EXCLUDED.author,
    client = EXCLUDED.client,
    summary = EXCLUDED.summary,
    extraction_json = EXCLUDED.extraction_json,
    extraction_schema_version = EXCLUDED.extraction_schema_version,
    extraction_model = EXCLUDED.extraction_model,
    updated_at = now()
"""

_INSERT_CHUNK = """
INSERT INTO public.document_chunks (
    chunk_id, document_id, chunk_index, section, page_from, page_to,
    chunk_raw, chunk_text, token_count, embedding
) VALUES (
    %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s::vector
)
"""


def to_pgvector(values: Any) -> str:
    """Format an embedding as a pgvector literal."""
    return "[" + ",".join(f"{float(value):.6f}" for value in values) + "]"


def parse_report_date(value: Any) -> date | None:
    """Parse an ISO date string, returning None when absent or malformed.

    The extraction prompt asks for YYYY-MM-DD, but a model can still return a
    partial date. A bad date must not fail the whole import.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        logger.warning("Unparsable report_date %r; storing NULL (value stays in extraction_json)", value)
        return None


def _optional_int(value: Any) -> int | None:
    """Convert a possibly-NaN pandas value to int or None."""
    if value is None or pd.isna(value):
        return None
    return int(value)


def import_document(cursor, payload: dict[str, Any], frame: pd.DataFrame) -> int:
    """Upsert one document and replace its chunks. Returns the chunk count."""
    extraction = payload.get("extraction", {})
    document_id = payload["document_id"]

    cursor.execute(
        _INSERT_DOCUMENT,
        (
            document_id,
            payload["source_file"],
            payload["source_sha256"],
            payload.get("markdown_path"),
            extraction.get("title"),
            extraction.get("report_type"),
            extraction.get("locality"),
            parse_report_date(extraction.get("report_date")),
            extraction.get("author"),
            extraction.get("client"),
            extraction.get("summary"),
            json.dumps(extraction, ensure_ascii=False),
            payload.get("extraction_schema_version"),
            payload.get("extraction_model"),
        ),
    )

    # Replace rather than upsert: chunk counts change when parameters change.
    cursor.execute("DELETE FROM public.document_chunks WHERE document_id = %s", (document_id,))

    rows = [
        (
            row.chunk_id,
            row.document_id,
            int(row.chunk_index),
            row.section,
            _optional_int(row.page_from),
            _optional_int(row.page_to),
            row.chunk_raw,
            row.chunk_text,
            _optional_int(row.token_count),
            to_pgvector(row.embedding),
        )
        for row in frame.itertuples(index=False)
    ]
    cursor.executemany(_INSERT_CHUNK, rows)
    return len(rows)


def needs_import(entry: dict[str, Any], force: bool) -> bool:
    """Decide whether a document must be re-imported."""
    if force:
        return True
    if not entry.get(timestamp_key("import")):
        return True
    # Chunking newer than the last import means the database is stale.
    chunked_at = entry.get(timestamp_key("chunk"))
    imported_at = entry.get(timestamp_key("import"))
    return bool(chunked_at and imported_at and chunked_at > imported_at)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Import geological reports into PostgreSQL.")
    parser.add_argument("--force", action="store_true", help="Re-import even when up to date")
    parser.add_argument("--only", nargs="*", help="Import only these document stems")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    configure_logging()
    args = parse_args(argv if argv is not None else sys.argv[1:])
    manifest = Manifest(MANIFEST_PATH)

    targets: list[tuple[str, str]] = []
    for key in manifest.keys():
        stem = Path(key).stem
        if args.only and stem not in args.only and key not in args.only:
            continue
        entry = manifest.get(key)
        if not entry.get(timestamp_key("chunk")):
            continue
        if needs_import(entry, args.force):
            targets.append((stem, key))

    if not targets:
        logger.info("Nothing to import; the database is up to date")
        return 0

    connection = psycopg2.connect(**load_connection_params())
    imported = 0
    failed = 0
    try:
        for stem, key in targets:
            extracted_path = EXTRACTED_DIR / f"{stem}.json"
            chunks_path = CHUNKS_DIR / f"{stem}.parquet"
            if not extracted_path.exists() or not chunks_path.exists():
                logger.error("Missing artifacts for %s; run the earlier stages first", stem)
                failed += 1
                continue

            payload = json.loads(extracted_path.read_text(encoding="utf-8"))
            frame = pd.read_parquet(chunks_path)

            cursor = connection.cursor()
            try:
                count = import_document(cursor, payload, frame)
                connection.commit()
                imported += 1
                manifest.update(key, imported_at=utc_now(), chunk_count=count)
                manifest.save()
                logger.info("Imported %s: 1 document, %d chunks", stem, count)
            except Exception as exc:  # noqa: BLE001 - keep going with the next document
                connection.rollback()
                failed += 1
                logger.exception("Failed importing %s: %s", stem, exc)
            finally:
                cursor.close()

        cursor = connection.cursor()
        cursor.execute("SELECT count(*) FROM public.documents")
        document_count = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM public.document_chunks")
        chunk_count = cursor.fetchone()[0]
        cursor.close()
        logger.info("Database now holds %d documents and %d chunks", document_count, chunk_count)
    finally:
        connection.close()

    logger.info("Import done: %d succeeded, %d failed", imported, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
