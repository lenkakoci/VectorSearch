"""Search the imported reports from the command line.

Modes, chosen with ``--mode``: ``vector`` (default), ``fts`` (no API call at
all), ``hybrid`` (both, merged by Reciprocal Rank Fusion) and ``rerank``
(forty hybrid candidates graded 0-3 by Gemini and reordered by grade). The
modes, the queries and the scores are documented in ``search_service.py`` and
``rerank_service.py``, which do the work; this file only parses arguments and
prints.

For an answer rather than passages, see ``ask_reports.py``.

Every mode can be restricted by metadata, either inline or as flags:

    search_reports.py "autor:Poul obec:Lednice hladina vody" --mode hybrid
    search_reports.py "hladina vody" --autor Poul --obec Lednice --mode hybrid
    search_reports.py "sonda S-2" --kind annex --mode fts
    search_reports.py --list --od 2019

Filtering is not a fourth kind of search: both branches are already SQL, so a
restriction is just more ``WHERE``. See ``search_filters.py`` for the vocabulary
and for why the clause is never built out of user text.

Run from data/scripts:
    uv run python search_reports.py "hladina podzemni vody"
    uv run python search_reports.py "unosnost zakladove spary" --hybrid --limit 5
    uv run python search_reports.py "Jak hluboko je voda v Lednici?" --mode rerank
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

import psycopg2

from pipeline_common import configure_logging, load_connection_params, load_settings
from rerank_service import MAX_GRADE, RerankUnavailable
from search_filters import Filters, add_filter_arguments, filters_from_query_and_args
from search_service import (
    MODES,
    RERANK_MODE,
    EmbeddingUnavailable,
    list_documents,
    run_search,
)

logger = logging.getLogger(__name__)

CLI_MODES = MODES + (RERANK_MODE,)

_SCORE_KEY = {"vector": "vector_score", "fts": "fts_score", "hybrid": "rrf_score"}
_HEADER = {"vector": "Vektorove", "fts": "Fulltextove", "hybrid": "Hybridni", "rerank": "Rerankovane"}


def _score(row: dict[str, Any], mode: str) -> str:
    """Return the score a result is ranked by, as printed."""
    if mode == RERANK_MODE:
        grade = row.get("rerank_grade")
        return "bez znamky" if grade is None else f"znamka {grade}/{MAX_GRADE}"
    value = row.get(_SCORE_KEY[mode])
    return "-" if value is None else f"{value:.4f}"


def render(rows: list[dict[str, Any]], mode: str) -> None:
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
        text = row.get("snippet") or ""
        print(f"\n{position}. [{_score(row, mode)}] {row.get('title') or '(bez nazvu)'}")
        kind = " | PŘÍLOHA" if row.get("content_kind") == "annex" else ""
        print(f"   sekce: {location}{pages} | chunk #{row['chunk_index']}{kind}")
        if mode == RERANK_MODE:
            print(f"   reranker: {row.get('rerank_reason') or '-'} | kandidat #{row.get('candidate_rank')}")
        print(f"   {text[:220]}...")
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
        choices=CLI_MODES,
        help="vector (default), fts (no API call), hybrid, or rerank (grades candidates with Gemini)",
    )
    parser.add_argument(
        "--hybrid", action="store_true", help="Alias for --mode hybrid"
    )
    parser.add_argument(
        "--list", action="store_true", dest="list_documents",
        help="List the documents matching the filter instead of searching their text",
    )
    parser.add_argument("--limit", type=int, default=5, help="Number of results (default: 5)")
    add_filter_arguments(parser)
    return parser.parse_args(argv)


def resolve_filters(args: argparse.Namespace) -> tuple[str, Filters]:
    """Return the search text and the filters from both prefixes and flags."""
    return filters_from_query_and_args(args.query, args)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    configure_logging()
    args = parse_args(argv if argv is not None else sys.argv[1:])
    settings = load_settings()

    mode = args.mode or ("hybrid" if args.hybrid else "vector")
    query, filters = resolve_filters(args)
    summary = filters.describe()

    if not args.list_documents and not query:
        logger.error("Nothing to search for. Give a query, or use --list to list documents.")
        return 1

    connection = psycopg2.connect(**load_connection_params())
    try:
        if args.list_documents:
            if query:
                logger.warning("--list ignores the query text %r", query)
            print(f"\nDokumenty | filtr: {summary or '(zadny)'}")
            render_documents(list_documents(connection, filters))
            return 0

        print(f"\n{_HEADER[mode]} vyhledavani: {query!r}")
        if summary:
            print(f"  filtr: {summary}")

        try:
            result = run_search(connection, query, mode, filters, args.limit, settings)
        except EmbeddingUnavailable as exc:
            logger.error(
                "Could not embed the query (%s). Full text alone needs no API: "
                "re-run with --mode fts.",
                exc,
            )
            return 1
        except RerankUnavailable as exc:
            logger.error("Could not grade the candidates (%s). --mode hybrid needs no grading.", exc)
            return 1

        if mode == "hybrid":
            print(
                f"  vektorove: {result.debug.get('vector_candidates', 0)} kandidatu"
                f" | full-text: {result.debug.get('fts_candidates', 0)} kandidatu"
            )
        elif mode == RERANK_MODE:
            stats = result.debug.get("rerank", {})
            print(
                f"  kandidatu: {stats.get('candidates', 0)}"
                f" | se znamkou >= {stats.get('min_grade')}: {stats.get('passed', 0)}"
                f" | {stats.get('model')}: {stats.get('calls', 0)} volani, {stats.get('ms', 0)} ms"
            )
        render(result.hits, mode)
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
