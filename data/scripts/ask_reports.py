"""Ask the reports a question from the command line.

Retrieval, reranking, the relevance gate, context and one model call happen in
``answer_service.py``; this file parses arguments and prints. Every sentence
of the answer carries the sources it cites and a verdict from
``citation_check.py``, so what is printed can be audited on the spot.

The same metadata filters as ``search_reports.py``, inline or as flags:

    ask_reports.py "Jak hluboko je voda v Lednici?" --obec Lednice
    ask_reports.py "obec:Roudno Kolik vrtu pro tepelne cerpadlo se navrhuje?"

Run from data/scripts:
    uv run python ask_reports.py "Jaka je vydatnost vrtu HV-979/3?"
    uv run python ask_reports.py "..." --show-prompt --max-sources 6
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

import psycopg2

import answer_log
from answer_service import NO_EVIDENCE, AnswerResult, AnswerUnavailable, answer
from citation_check import VERIFIED
from context_builder import MAX_SOURCES, PER_DOCUMENT, TOKEN_BUDGET
from pipeline_common import ANSWERS_DIR, configure_logging, load_connection_params, load_settings
from rerank_service import MAX_GRADE, MIN_GRADE, RerankUnavailable
from search_filters import add_filter_arguments, filters_from_query_and_args
from search_service import CANDIDATES, EmbeddingUnavailable

logger = logging.getLogger(__name__)

_STATUS = {
    "answered": "Odpovezeno",
    "partial": "Castecne",
    "insufficient": "Nedostatek podkladu",
    NO_EVIDENCE: "Bez podkladu",
}


def _pages(source: dict[str, Any]) -> str:
    """Return the page range of a source, empty when it has none."""
    start, end = source.get("page_from"), source.get("page_to")
    if not start:
        return ""
    return f", s. {start}" if not end or end == start else f", s. {start}-{end}"


def render(result: AnswerResult) -> None:
    """Print an answer, its sources and how it was produced."""
    print(f"\nStav: {_STATUS.get(result.status, result.status)}")

    if result.status == NO_EVIDENCE:
        gate = result.trace.get("gate", {})
        print(
            f"  Zadny z {gate.get('candidates', 0)} kandidatu nedosahl znamky {gate.get('min_grade')}."
            " Model se nevolal."
        )
    for position, statement in enumerate(result.statements, start=1):
        marks = "".join(f"[{value}]" for value in statement["source_ids"])
        flag = "" if statement["check"] == VERIFIED else f"   [!] {statement['note']}"
        print(f"\n{position}. {statement['text']} {marks}{flag}")

    if result.missing:
        print("\nVe zdrojich chybi:")
        for item in result.missing:
            print(f"  - {item}")

    if result.conflicts:
        print("\nRozpory mezi zdroji:")
        for conflict in result.conflicts:
            marks = "".join(f"[{value}]" for value in conflict["source_ids"])
            print(f"  - {conflict['topic']}: {conflict['description']} {marks}")

    if result.sources:
        header = "Nejblizsi nalezene uryvky" if result.status == NO_EVIDENCE else "Zdroje"
        print(f"\n{header}:")
        for source in result.sources:
            grade = source.get("rerank_grade")
            grade_text = "" if grade is None else f" | znamka {grade}/{MAX_GRADE}"
            cited = " | citovano" if source.get("cited") else ""
            role = source.get("role") or ""
            print(f"\n [{source['id']}] {source.get('title') or '(bez nazvu)'}")
            print(
                f"     {source.get('section') or '-'}{_pages(source)}"
                f" | chunk #{source['chunk_index']} | {role}{grade_text}{cited}"
            )
            print(f"     {' '.join((source.get('chunk_raw') or '').split())[:200]}...")

    context = result.trace.get("context", {})
    generation = result.trace.get("generation", {})
    validation = result.trace.get("validation", {})
    gate = result.trace.get("gate", {})
    print(
        f"\nPruben: kandidatu {gate.get('candidates', 0)}"
        f" | branou proslo {gate.get('passed', 0)}"
        f" | zdroju {context.get('sources', 0)}"
        f" ({context.get('neighbours', 0)} jako kontext)"
        f" | kontext {context.get('tokens', 0)} tokenu"
    )
    print(
        f"        model {result.model} v{result.prompt_version}"
        f" | overeno {validation.get('verified', 0)} z {validation.get('statements', 0)} vet"
        f" | generovani {generation.get('ms', 0)} ms"
        f" | celkem {result.trace.get('total_ms', 0)} ms"
    )
    print()


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Ask the geological reports a question.")
    parser.add_argument("question", help="Question in Czech")
    parser.add_argument("--candidates", type=int, default=CANDIDATES, help=f"Candidates to grade (default: {CANDIDATES})")
    parser.add_argument("--min-grade", type=int, default=MIN_GRADE, choices=range(0, MAX_GRADE + 1), help="Relevance gate")
    parser.add_argument("--max-sources", type=int, default=MAX_SOURCES, help=f"Sources in the context (default: {MAX_SOURCES})")
    parser.add_argument("--per-document", type=int, default=PER_DOCUMENT, help="Sources from one report in the first pass")
    parser.add_argument("--token-budget", type=int, default=TOKEN_BUDGET, help="Token budget for the evidence")
    parser.add_argument("--no-neighbours", action="store_true", help="Do not add neighbouring chunks of split sections")
    parser.add_argument("--show-prompt", action="store_true", help="Print the prompt the model received")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Print the whole result as JSON")
    parser.add_argument("--no-log", action="store_true", help="Do not append this answer to the JSONL log")
    parser.add_argument("--fresh", action="store_true", help="Ignore a stored answer and pay for a new one")
    parser.add_argument("--no-cache", action="store_true", help="Neither read nor write the answer cache")
    add_filter_arguments(parser)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    configure_logging()
    args = parse_args(argv if argv is not None else sys.argv[1:])
    settings = load_settings()

    question, filters = filters_from_query_and_args(args.question, args)
    if not question:
        logger.error("The question is only filters; give it some text as well.")
        return 1

    connection = psycopg2.connect(**load_connection_params())
    try:
        result = answer(
            connection,
            question,
            filters,
            settings=settings,
            candidates=args.candidates,
            min_grade=args.min_grade,
            max_sources=args.max_sources,
            token_budget=args.token_budget,
            per_document=args.per_document,
            use_neighbours=not args.no_neighbours,
            cache_dir=None if args.no_cache else ANSWERS_DIR,
            fresh=args.fresh,
        )
    except EmbeddingUnavailable as exc:
        logger.error("Could not embed the question (%s).", exc)
        return 1
    except RerankUnavailable as exc:
        logger.error("Could not grade the candidates (%s).", exc)
        return 1
    except AnswerUnavailable as exc:
        logger.error("Could not get an answer (%s). Search still works: try search_reports.py.", exc)
        return 1
    finally:
        connection.close()

    # Real questions are the raw material of the next golden set, so what was
    # asked is kept even when the answer itself is read once and forgotten.
    if not args.no_log:
        answer_log.append(answer_log.record(result, source="cli", filters=filters.as_dict()))

    if args.as_json:
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, default=str))
        return 0

    summary = filters.describe()
    print(f"\nOtazka: {question!r}")
    if summary:
        print(f"  filtr: {summary}")
    render(result)
    if args.show_prompt:
        print("--- prompt ---")
        print(result.trace.get("prompt", "(nezachycen)"))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
