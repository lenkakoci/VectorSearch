"""Measure the answers, not only the retrieval.

``eval_retrieval.py`` asks whether the right chunk was found.
This asks what happened next: did the answer cite it, did every sentence
survive the citation check, and did the pipeline stay silent on the questions
the corpus cannot answer.

Reported over the same golden set:

- status of each answer: answered, partial, insufficient or no_evidence;
- cited the expected evidence: the answer quotes a chunk the golden set names
  as the place that answers the question, which is the strictest check we can
  run without a human;
- verified sentences: the share that passed ``citation_check.py``, so a quote
  was found in the cited chunk and every number in the sentence was there too;
- refusals: for a question with no answer in the corpus, silence is the right
  answer. ``no_evidence`` or ``insufficient`` counts as correct, anything else
  is a false answer and the worst failure this system can have.

Cost per question: one query embedding, up to two grading calls for candidates
not graded before, and one answering call. Nothing here is cached between
runs, so a full run over the golden set is paid every time.

Run from data/scripts:
    uv run python eval_answers.py --only lednice-hladina neg-jihlava
    uv run python eval_answers.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2

from answer_service import NO_EVIDENCE, AnswerResult, AnswerUnavailable, answer
from citation_check import VERIFIED
from context_builder import MAX_SOURCES, PER_DOCUMENT, TOKEN_BUDGET
from eval_retrieval import (
    GOLDEN_PATH,
    QUESTION_TYPES,
    RESULTS_DIR,
    Question,
    load_golden,
    load_stems,
    select_questions,
)
from pipeline_common import configure_logging, load_connection_params, load_settings
from rerank_service import MAX_GRADE, MIN_GRADE, RerankUnavailable
from search_filters import Filters
from search_service import CANDIDATES, EmbeddingUnavailable

logger = logging.getLogger(__name__)

ANSWER_STATUSES = ("answered", "partial", "insufficient", NO_EVIDENCE)
REFUSALS = ("insufficient", NO_EVIDENCE)


def evidence_in(sources: list[dict[str, Any]], question: Question, stems: dict[str, str]) -> bool:
    """Return whether any of these sources is a place the golden set expects."""
    return any(
        item.matches(stems.get(str(source["document_id"]), ""), source.get("chunk_raw"))
        for source in sources
        for item in question.evidence
    )


def evaluate_answer(
    question: Question, result: AnswerResult, stems: dict[str, str]
) -> dict[str, Any]:
    """Score one answered question."""
    cited = [source for source in result.sources if source.get("cited")]
    verified = sum(1 for statement in result.statements if statement["check"] == VERIFIED)
    validation = result.trace.get("validation", {})
    context = result.trace.get("context", {})
    gate = result.trace.get("gate", {})
    return {
        "id": question.id,
        "type": question.type,
        "question": question.question,
        "negative": question.negative,
        "status": result.status,
        "statements": len(result.statements),
        "verified": verified,
        "flagged": [statement["check"] for statement in result.statements if statement["check"] != VERIFIED],
        # The sentence itself, so a failed check can be judged without re-running the question.
        "flagged_details": [
            {"text": statement["text"], "check": statement["check"], "note": statement["note"]}
            for statement in result.statements
            if statement["check"] != VERIFIED
        ],
        "cited_expected": evidence_in(cited, question, stems) if not question.negative else False,
        "expected_in_context": evidence_in(result.sources, question, stems) if not question.negative else False,
        "refused": result.status in REFUSALS,
        "sources": len(result.sources),
        "cited_sources": len(cited),
        "missing": result.missing,
        "conflicts": len(result.conflicts),
        "passed_gate": gate.get("passed"),
        "context_tokens": context.get("tokens"),
        "ms": result.trace.get("total_ms"),
        "validation": validation.get("checks"),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the rows into the numbers worth comparing between runs."""
    answerable = [row for row in rows if not row["negative"]]
    unanswerable = [row for row in rows if row["negative"]]
    statements = sum(row["statements"] for row in answerable)
    verified = sum(row["verified"] for row in answerable)
    return {
        "questions": len(rows),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "status": {status: sum(1 for row in rows if row["status"] == status) for status in ANSWER_STATUSES},
        "cited_expected": sum(1 for row in answerable if row["cited_expected"]),
        "expected_in_context": sum(1 for row in answerable if row["expected_in_context"]),
        "refused_answerable": sum(1 for row in answerable if row["refused"]),
        "statements": statements,
        "verified_statements": verified,
        "refused_unanswerable": sum(1 for row in unanswerable if row["refused"]),
        "false_answers": sum(1 for row in unanswerable if not row["refused"]),
        "median_ms": sorted(row["ms"] or 0 for row in rows)[len(rows) // 2] if rows else 0,
    }


def print_report(rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    """Print the evaluation for a terminal."""
    print(f"\nOdpovědi nad zlatou sadou: {summary['answerable']} otázek s odpovědí, {summary['unanswerable']} bez odpovědi")

    print("\nStav odpovědi")
    for status in ANSWER_STATUSES:
        print(f"  {status:<14}{summary['status'][status]:>4}")

    print("\nOtázky s odpovědí")
    print(f"  očekávaný úryvek byl v kontextu   {summary['expected_in_context']:>3} z {summary['answerable']}")
    print(f"  odpověď ho i citovala             {summary['cited_expected']:>3} z {summary['answerable']}")
    print(f"  systém odmítl odpovědět           {summary['refused_answerable']:>3} z {summary['answerable']}")
    print(f"  ověřených vět                     {summary['verified_statements']:>3} z {summary['statements']}")

    print("\nOtázky bez odpovědi")
    print(f"  systém správně neodpověděl        {summary['refused_unanswerable']:>3} z {summary['unanswerable']}")
    print(f"  vymyšlená odpověď                 {summary['false_answers']:>3} z {summary['unanswerable']}")

    print(f"\n{'otázka':<24}{'typ':<12}{'stav':<14}{'vět':>5}{'ověř.':>6}{'citoval':>9}{'ms':>8}")
    for row in rows:
        cited = "-" if row["negative"] else ("ano" if row["cited_expected"] else "ne")
        print(
            f"{row['id']:<24}{row['type']:<12}{row['status']:<14}"
            f"{row['statements']:>5}{row['verified']:>6}{cited:>9}{int(row['ms'] or 0):>8}"
        )

    flagged = [row for row in rows if row["flagged"]]
    if flagged:
        print("\nVěty, které neprošly kontrolou")
        for row in flagged:
            print(f"  {row['id']:<24}{', '.join(row['flagged'])}")
    print()


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Measure answer quality against the golden set.")
    parser.add_argument("--only", nargs="+", metavar="ID", help="Evaluate only these question ids")
    parser.add_argument("--type", nargs="+", choices=QUESTION_TYPES, dest="types", help="Evaluate only these question types")
    parser.add_argument("--candidates", type=int, default=CANDIDATES, help=f"Candidates to grade (default: {CANDIDATES})")
    parser.add_argument("--min-grade", type=int, default=MIN_GRADE, choices=range(0, MAX_GRADE + 1), help="Relevance gate")
    parser.add_argument("--max-sources", type=int, default=MAX_SOURCES, help=f"Sources in the context (default: {MAX_SOURCES})")
    parser.add_argument("--per-document", type=int, default=PER_DOCUMENT, help="Sources from one report in the first pass")
    parser.add_argument("--token-budget", type=int, default=TOKEN_BUDGET, help="Token budget for the evidence")
    parser.add_argument("--no-neighbours", action="store_true", help="Do not add neighbouring chunks")
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH, help="Golden set file")
    parser.add_argument("--out", type=Path, help="JSON results file (default: processed/eval/answers-<time>.json)")
    parser.add_argument("--no-save", action="store_true", help="Print the report without writing JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    configure_logging()
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        version, questions = load_golden(args.golden)
        questions = select_questions(questions, args.only, args.types)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    if not questions:
        logger.error("No question matches --only / --type")
        return 1

    settings = load_settings()
    connection = psycopg2.connect(**load_connection_params())
    rows: list[dict[str, Any]] = []
    try:
        stems = load_stems(connection)
        for number, question in enumerate(questions, start=1):
            logger.info("[%d/%d] %s", number, len(questions), question.id)
            try:
                result = answer(
                    connection,
                    question.question,
                    Filters(),
                    settings=settings,
                    candidates=args.candidates,
                    min_grade=args.min_grade,
                    max_sources=args.max_sources,
                    per_document=args.per_document,
                    token_budget=args.token_budget,
                    use_neighbours=not args.no_neighbours,
                    keep_prompt=False,
                )
            except (EmbeddingUnavailable, RerankUnavailable, AnswerUnavailable) as exc:
                logger.error("Stopped at %r: %s", question.id, exc)
                return 1
            rows.append(evaluate_answer(question, result, stems))
    finally:
        connection.close()

    summary = summarize(rows)
    print_report(rows, summary)

    if not args.no_save:
        path = args.out or RESULTS_DIR / f"answers-{datetime.now():%Y%m%d-%H%M%S}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "golden": {"path": str(args.golden), "version": version, "questions": len(questions)},
                    "settings": {
                        "candidates": args.candidates,
                        "min_grade": args.min_grade,
                        "max_sources": args.max_sources,
                        "per_document": args.per_document,
                        "token_budget": args.token_budget,
                        "neighbours": not args.no_neighbours,
                        "answer_model": settings.answer_model,
                        "rerank_model": settings.rerank_model,
                    },
                    "summary": summary,
                    "questions": rows,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"Výsledky: {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
