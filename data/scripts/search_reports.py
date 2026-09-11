"""Search the imported reports from the command line.

Three modes, chosen with ``--mode``: ``vector`` (default), ``fts`` (no API call
at all) and ``hybrid`` (both, merged by Reciprocal Rank Fusion). The modes, the
queries and the scores are documented in ``search_service.py``, which does the
work; this file only parses arguments and prints.

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
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

import psycopg2

from pipeline_common import configure_logging, load_connection_params, load_settings
from search_filters import CONTENT_KINDS, Filters, build_filters, parse_query
from search_service import (
    MODES,
    EmbeddingUnavailable,
    list_documents,
    run_search,
)

logger = logging.getLogger(__name__)

_SCORE_KEY = {"vector": "vector_score", "fts": "fts_score", "hybrid": "rrf_score"}
_HEADER = {"vector": "Vektorove", "fts": "Fulltextove", "hybrid": "Hybridni"}


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
        text = row.get("snippet") or ""
        print(f"\n{position}. [{row[score_key]:.4f}] {row.get('title') or '(bez nazvu)'}")
        kind = " | PŘÍLOHA" if row.get("content_kind") == "annex" else ""
        print(f"   sekce: {location}{pages} | chunk #{row['chunk_index']}{kind}")
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
        choices=MODES,
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
    group.add_argument(
        "--kind", "--druh", dest="content_kind", choices=CONTENT_KINDS,
        help="prose = report body, annex = borehole logs and forms (no vector, full text only)",
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
        content_kind=args.content_kind,
    )
    return text, inline.merge(flags)


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

        if mode == "hybrid":
            print(
                f"  vektorove: {result.debug.get('vector_candidates', 0)} kandidatu"
                f" | full-text: {result.debug.get('fts_candidates', 0)} kandidatu"
            )
        render(result.hits, _SCORE_KEY[mode])
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
