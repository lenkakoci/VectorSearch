"""Search the imported reports from the command line.

Three modes, chosen with ``--mode``:

- ``vector`` (default): embed the query, rank by cosine distance over the HNSW
  index.
- ``fts``: full text only. Makes **no API call at all**, so it costs nothing, is
  not subject to the embedding quota, and works without a Gemini key.
- ``hybrid``: run both and merge the rankings with Reciprocal Rank Fusion. Vector
  search is weak at exact tokens - borehole ids like V-3, parcel numbers,
  standard references - and full text is weak at paraphrase. RRF needs no score
  normalisation between the two.

Every mode can be restricted by metadata, either inline or as flags:

    search_reports.py "autor:Poul obec:Lednice hladina vody" --mode hybrid
    search_reports.py "hladina vody" --autor Poul --obec Lednice --mode hybrid
    search_reports.py --list --od 2019

Filtering is not a fourth kind of search: both branches are already SQL, so a
restriction is just more ``WHERE``. See ``search_filters.py`` for the vocabulary
and for why the clause is never built out of user text.

The full-text side asks both Czech configurations from
sql/tables/03_create_czech_fts.sql: ``czech`` matches across inflection, and
``czech_literal`` matches a query typed without diacritics. Chunks are indexed
under both, so OR-ing the two queries finds whatever either one would.

``websearch_to_tsquery`` rather than ``plainto_tsquery``: it understands quoted
phrases, ``or`` and ``-word``, and unlike ``to_tsquery`` it never raises on
whatever the user types. Terms are still ANDed by default, which only became
workable once the dictionary made inflected forms meet and dropped stop words.

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
from gemini_auth import create_gemini_client, is_retryable_error, normalize
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from pipeline_common import configure_logging, load_connection_params, load_settings
from search_filters import Filters, build_filters, parse_query

logger = logging.getLogger(__name__)

# Standard RRF damping constant; keeps any single ranking from dominating.
RRF_K = 60

_VECTOR_QUERY = """
SELECT c.chunk_id, c.document_id, c.chunk_index, c.section, c.page_from, c.page_to,
       c.chunk_raw, d.title, d.locality, d.report_date,
       1 - (c.embedding <=> %s::vector) AS score
FROM public.document_chunks c
JOIN public.documents d ON d.id = c.document_id
WHERE c.embedding IS NOT NULL{filters}
ORDER BY c.embedding <=> %s::vector
LIMIT %s
"""

_FTS_QUERY = """
SELECT c.chunk_id, c.document_id, c.chunk_index, c.section, c.page_from, c.page_to,
       c.chunk_raw, d.title, d.locality, d.report_date,
       ts_rank(c.fts_chunk, query) AS score
FROM public.document_chunks c
JOIN public.documents d ON d.id = c.document_id,
     LATERAL (
         SELECT websearch_to_tsquery('public.czech', %s::text)
                || websearch_to_tsquery('public.czech_literal', %s::text)
     ) AS q(query)
WHERE c.fts_chunk @@ query{filters}
ORDER BY score DESC
LIMIT %s
"""

_LIST_QUERY = """
SELECT d.id, d.title, d.author, d.report_date,
       d.extraction_json->>'municipality' AS municipality,
       count(c.chunk_id) AS chunks
FROM public.documents d
LEFT JOIN public.document_chunks c ON c.document_id = d.id
WHERE TRUE{filters}
GROUP BY d.id
ORDER BY d.report_date DESC NULLS LAST, d.title
"""


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    retry=retry_if_exception(is_retryable_error),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def embed_query(text: str, model: str, dimensions: int) -> list[float]:
    """Embed the query with the same model and dimensionality as the corpus.

    ``task_type=RETRIEVAL_QUERY`` is the counterpart to RETRIEVAL_DOCUMENT used
    when embedding chunks. Both sides of the pair must match, otherwise the query
    lands in a different region of the embedding space than the corpus.

    Retried like the ingestion calls are: one search is one request, and the
    embedding quota is counted per request per minute, so a handful of searches
    in quick succession is enough to meet a 429.
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
        print("Zadna shoda.")
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


def render_documents(rows: list[dict[str, Any]]) -> None:
    """Print the documents matching a filter."""
    if not rows:
        print("Zadny dokument neodpovida filtru.")
        return
    for row in rows:
        print(f"\n{row['id']}  {row.get('title') or '(bez nazvu)'}")
        print(
            f"   obec: {row.get('municipality') or '-'}"
            f" | autor: {row.get('author') or '-'}"
            f" | datum: {row.get('report_date') or '-'}"
            f" | {row['chunks']} chunku"
        )
    print()


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Search geological reports.")
    parser.add_argument("query", nargs="?", default="", help="Search query")
    parser.add_argument(
        "--mode",
        choices=("vector", "fts", "hybrid"),
        help="vector (default), fts (no API call), or hybrid",
    )
    parser.add_argument(
        "--hybrid", action="store_true", help="Alias for --mode hybrid"
    )
    parser.add_argument(
        "--list", action="store_true", dest="list_documents",
        help="List the documents matching the filter instead of searching their text",
    )
    parser.add_argument("--limit", type=int, default=5, help="Number of results (default: 5)")

    group = parser.add_argument_group("filters (also usable inline as autor:Poul)")
    group.add_argument("--autor", "--author", dest="author")
    group.add_argument("--klient", "--client", dest="client")
    group.add_argument("--lokalita", "--locality", dest="locality")
    group.add_argument("--obec", "--municipality", dest="municipality")
    group.add_argument("--typ", "--type", dest="report_type")
    group.add_argument("--org", dest="organization")
    group.add_argument("--od", "--from", dest="date_from", help="YYYY, YYYY-MM or YYYY-MM-DD")
    group.add_argument("--do", "--to", dest="date_to", help="YYYY, YYYY-MM or YYYY-MM-DD")
    group.add_argument(
        "--document", action="append", dest="document_ids",
        help="Restrict to this document UUID. Repeatable.",
    )
    return parser.parse_args(argv)


def resolve_filters(args: argparse.Namespace) -> tuple[str, Filters]:
    """Return the search text and the filters from both prefixes and flags."""
    text, inline = parse_query(args.query)
    flags = build_filters(
        author=args.author,
        client=args.client,
        locality=args.locality,
        municipality=args.municipality,
        report_type=args.report_type,
        organization=args.organization,
        date_from=args.date_from,
        date_to=args.date_to,
        document_ids=args.document_ids,
    )
    return text, inline.merge(flags)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    configure_logging()
    args = parse_args(argv if argv is not None else sys.argv[1:])
    settings = load_settings()

    mode = args.mode or ("hybrid" if args.hybrid else "vector")
    query, filters = resolve_filters(args)
    filter_sql, filter_params = filters.where()
    summary = filters.describe()

    if not args.list_documents and not query:
        logger.error("Nothing to search for. Give a query, or use --list to list documents.")
        return 1

    connection = psycopg2.connect(**load_connection_params())
    try:
        cursor = connection.cursor()

        if args.list_documents:
            if query:
                logger.warning("--list ignores the query text %r", query)
            cursor.execute(_LIST_QUERY.format(filters=filter_sql), filter_params)
            rows = _rows_to_dicts(cursor)
            cursor.close()
            print(f"\nDokumenty | filtr: {summary or '(zadny)'}")
            render_documents(rows)
            return 0

        # Over-fetch each branch so fusion has something to work with.
        fetch = args.limit * 4 if mode == "hybrid" else args.limit
        header = {"vector": "Vektorove", "fts": "Fulltextove", "hybrid": "Hybridni"}[mode]
        print(f"\n{header} vyhledavani: {query!r}")
        if summary:
            print(f"  filtr: {summary}")

        vector_rows: list[dict[str, Any]] = []
        if mode in ("vector", "hybrid"):
            try:
                literal = to_pgvector(
                    embed_query(query, settings.embedding_model, settings.embedding_dimensions)
                )
            except Exception as exc:  # noqa: BLE001 - the fallback is worth naming
                logger.error(
                    "Could not embed the query (%s). Full text alone needs no API: "
                    "re-run with --mode fts.",
                    type(exc).__name__,
                )
                return 1
            cursor.execute(
                _VECTOR_QUERY.format(filters=filter_sql),
                [literal, *filter_params, literal, fetch],
            )
            vector_rows = _rows_to_dicts(cursor)

        fts_rows: list[dict[str, Any]] = []
        if mode in ("fts", "hybrid"):
            cursor.execute(
                _FTS_QUERY.format(filters=filter_sql),
                [query, query, *filter_params, fetch],
            )
            fts_rows = _rows_to_dicts(cursor)

        cursor.close()

        if mode == "vector":
            render(vector_rows[: args.limit], "score")
        elif mode == "fts":
            render(fts_rows[: args.limit], "score")
        else:
            print(
                f"  vektorove: {len(vector_rows)} kandidatu"
                f" | full-text: {len(fts_rows)} kandidatu"
            )
            render(reciprocal_rank_fusion([vector_rows, fts_rows], args.limit), "rrf")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
