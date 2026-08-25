"""Search the imported reports from the command line.

Two modes:

- vector (default): embed the query, rank by cosine distance over the HNSW index.
- hybrid (--hybrid): also run a full-text query and merge both rankings with
  Reciprocal Rank Fusion. Vector search is weak at exact tokens - borehole ids
  like V-3, parcel numbers, standard references - and full-text is weak at
  paraphrase. RRF needs no score normalisation between the two.

Run from data/scripts:
    uv run python search_reports.py "hladina podzemni vody"
    uv run python search_reports.py "unosnost zakladove spary" --hybrid --limit 5
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

import psycopg2
from google.genai import types
from gemini_auth import create_gemini_client, normalize

from pipeline_common import configure_logging, load_connection_params, load_settings

logger = logging.getLogger(__name__)

# Standard RRF damping constant; keeps any single ranking from dominating.
RRF_K = 60

_VECTOR_QUERY = """
SELECT c.chunk_id, c.document_id, c.chunk_index, c.section, c.page_from, c.page_to,
       c.chunk_raw, d.title, d.locality, d.report_date,
       1 - (c.embedding <=> %s::vector) AS score
FROM public.document_chunks c
JOIN public.documents d ON d.id = c.document_id
WHERE c.embedding IS NOT NULL
  AND (%s::uuid IS NULL OR c.document_id = %s::uuid)
ORDER BY c.embedding <=> %s::vector
LIMIT %s
"""

_FTS_QUERY = """
SELECT c.chunk_id, c.document_id, c.chunk_index, c.section, c.page_from, c.page_to,
       c.chunk_raw, d.title, d.locality, d.report_date,
       ts_rank(c.fts_chunk, query) AS score
FROM public.document_chunks c
JOIN public.documents d ON d.id = c.document_id,
     plainto_tsquery('simple', unaccent(%s::text)) AS query
WHERE c.fts_chunk @@ query
  AND (%s::uuid IS NULL OR c.document_id = %s::uuid)
ORDER BY score DESC
LIMIT %s
"""


def embed_query(text: str, model: str, dimensions: int) -> list[float]:
    """Embed the query with the same model and dimensionality as the corpus.

    ``task_type=RETRIEVAL_QUERY`` is the counterpart to RETRIEVAL_DOCUMENT used
    when embedding chunks. Both sides of the pair must match, otherwise the query
    lands in a different region of the embedding space than the corpus.
    """
    client = create_gemini_client()
    response = client.models.embed_content(
        model=model,
        contents=text,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=dimensions,
        ),
    )
    return normalize(response.embeddings[0].values)


def to_pgvector(values: list[float]) -> str:
    """Format an embedding as a pgvector literal."""
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


def _rows_to_dicts(cursor) -> list[dict[str, Any]]:
    """Convert a cursor result to a list of dicts."""
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def reciprocal_rank_fusion(
    rankings: list[list[dict[str, Any]]], limit: int
) -> list[dict[str, Any]]:
    """Merge several rankings by Reciprocal Rank Fusion."""
    fused: dict[str, dict[str, Any]] = {}
    for ranking in rankings:
        for rank, row in enumerate(ranking, start=1):
            key = str(row["chunk_id"])
            entry = fused.setdefault(key, {**row, "rrf": 0.0})
            entry["rrf"] += 1.0 / (RRF_K + rank)
    ordered = sorted(fused.values(), key=lambda row: row["rrf"], reverse=True)
    return ordered[:limit]


def render(rows: list[dict[str, Any]], score_key: str) -> None:
    """Print search results."""
    if not rows:
        print("No matches.")
        return
    for position, row in enumerate(rows, start=1):
        location = row.get("section") or "-"
        pages = ""
        if row.get("page_from"):
            pages = f", s. {row['page_from']}"
            if row.get("page_to") and row["page_to"] != row["page_from"]:
                pages = f", s. {row['page_from']}-{row['page_to']}"
        snippet = " ".join((row.get("chunk_raw") or "").split())[:220]
        print(f"\n{position}. [{row[score_key]:.4f}] {row.get('title') or '(bez nazvu)'}")
        print(f"   sekce: {location}{pages} | chunk #{row['chunk_index']}")
        print(f"   {snippet}...")
    print()


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Search geological reports.")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--hybrid", action="store_true", help="Combine vector and full-text search")
    parser.add_argument("--limit", type=int, default=5, help="Number of results (default: 5)")
    parser.add_argument("--document", help="Restrict the search to one document UUID")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    configure_logging()
    args = parse_args(argv if argv is not None else sys.argv[1:])
    settings = load_settings()

    # Over-fetch each branch so fusion has something to work with.
    fetch = args.limit * 4 if args.hybrid else args.limit

    vector_literal = to_pgvector(
        embed_query(args.query, settings.embedding_model, settings.embedding_dimensions)
    )

    connection = psycopg2.connect(**load_connection_params())
    try:
        cursor = connection.cursor()
        cursor.execute(
            _VECTOR_QUERY,
            (vector_literal, args.document, args.document, vector_literal, fetch),
        )
        vector_rows = _rows_to_dicts(cursor)

        if not args.hybrid:
            cursor.close()
            print(f"\nVektorove vyhledavani: {args.query!r}")
            render(vector_rows[: args.limit], "score")
            return 0

        cursor.execute(_FTS_QUERY, (args.query, args.document, args.document, fetch))
        fts_rows = _rows_to_dicts(cursor)
        cursor.close()

        print(f"\nHybridni vyhledavani: {args.query!r}")
        print(f"  vektorove: {len(vector_rows)} kandidatu | full-text: {len(fts_rows)} kandidatu")
        render(reciprocal_rank_fusion([vector_rows, fts_rows], args.limit), "rrf")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
