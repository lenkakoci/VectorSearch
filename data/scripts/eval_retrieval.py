"""Measure retrieval quality against a golden set of questions.

Until this script nothing measured relevance: ``check_pipeline.py`` verifies
artefacts, and whether a change to chunking or search helped was judged by
reading results. The golden set in ``data/eval/golden.yaml`` fixes realistic
Czech questions and, for each, the place in the corpus that answers it.

Relevance is decided by text, not by chunk id. Each question names its
evidence as a document stem plus a verbatim snippet the relevant chunk
contains, so the set survives re-chunking; ``text_match.py`` does the loose
comparison. A question has several evidence items when its answer is spread
over several places.

Reported per mode (``fts``, ``vector``, ``hybrid``) over the top ``--depth``:

- recall@k: share of a question's evidence items found in the top k;
- MRR: reciprocal rank of the first relevant chunk, 0 when none was found.

Questions without an answer in the corpus (type ``negative``) take no part in
recall or MRR. The report shows instead what retrieval still returns for them:
the vector branch always returns something, and a relevance gate in front of
any generated answer will have to reject exactly that.

Cost: one query embedding per question, because ``compare()`` embeds once for
all three modes. ``--modes fts`` makes no API call at all, and ``--check`` only
verifies the golden set against the database.

Run from data/scripts:
    uv run python eval_retrieval.py --check
    uv run python eval_retrieval.py
    uv run python eval_retrieval.py --type annex exact --modes fts
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

import psycopg2
import yaml

from pipeline_common import (
    DATA_DIR,
    PROCESSED_DIR,
    Settings,
    configure_logging,
    load_connection_params,
    load_settings,
)
from search_filters import Filters
from search_service import MODES, EmbeddingUnavailable, compare, run_search
from text_match import contains_normalized

logger = logging.getLogger(__name__)

GOLDEN_PATH = DATA_DIR / "eval" / "golden.yaml"
RESULTS_DIR = PROCESSED_DIR / "eval"
DEPTH = 40
CUTOFFS = (5, 10, 40)
QUESTION_TYPES = ("morphology", "exact", "paraphrase", "multi", "annex", "negative")

_SCORE_KEY = {"fts": "fts_score", "vector": "vector_score", "hybrid": "rrf_score"}


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip())


@dataclass(frozen=True)
class Evidence:
    """One place in the corpus that answers a question.

    ``doc`` is the source file stem. Any one of the ``contains`` snippets
    identifies the relevant chunk.
    """

    doc: str
    contains: tuple[str, ...]

    def matches(self, stem: str, text: str | None) -> bool:
        """Return whether a chunk of document ``stem`` with ``text`` is this evidence."""
        return _nfc(stem) == _nfc(self.doc) and any(
            contains_normalized(text, snippet) for snippet in self.contains
        )


@dataclass(frozen=True)
class Question:
    """One golden-set question and the evidence that answers it."""

    id: str
    type: str
    question: str
    evidence: tuple[Evidence, ...]

    @property
    def negative(self) -> bool:
        """Return whether the corpus holds no answer to this question."""
        return not self.evidence


def _parse_evidence(item: Any, where: str, problems: list[str]) -> Evidence | None:
    """Parse one evidence entry, recording problems instead of raising."""
    if not isinstance(item, dict):
        problems.append(f"{where}: evidence must be a mapping with doc and contains")
        return None
    doc = str(item.get("doc") or "").strip()
    raw = item.get("contains")
    snippets = [raw] if isinstance(raw, str) else list(raw or [])
    snippets = [str(snippet).strip() for snippet in snippets if str(snippet).strip()]
    if not doc:
        problems.append(f"{where}: evidence needs doc")
    if not snippets:
        problems.append(f"{where}: evidence needs contains")
    if not doc or not snippets:
        return None
    return Evidence(doc=_nfc(doc), contains=tuple(snippets))


def load_golden(path: Path = GOLDEN_PATH) -> tuple[int, list[Question]]:
    """Read and validate the golden set; return its version and questions.

    Raises:
        ValueError: Listing every problem found, not just the first.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    problems: list[str] = []
    questions: list[Question] = []
    seen: set[str] = set()

    for index, item in enumerate(raw.get("questions") or [], start=1):
        if not isinstance(item, dict):
            problems.append(f"question {index}: must be a mapping")
            continue
        qid = str(item.get("id") or "").strip()
        where = f"question {index} ({qid or 'no id'})"
        kind = str(item.get("type") or "").strip()
        text = " ".join(str(item.get("question") or "").split())

        if not qid:
            problems.append(f"{where}: id is missing")
        elif qid in seen:
            problems.append(f"{where}: id {qid!r} is already used")
        seen.add(qid)
        if kind not in QUESTION_TYPES:
            problems.append(f"{where}: unknown type {kind!r}; expected one of {', '.join(QUESTION_TYPES)}")
        if not text:
            problems.append(f"{where}: question text is missing")

        entries = item.get("evidence") or []
        if kind == "negative" and entries:
            problems.append(f"{where}: a negative question must not have evidence")
        if kind != "negative" and not entries:
            problems.append(f"{where}: a question with an answer needs evidence")
        evidence = [
            parsed
            for entry in entries
            if (parsed := _parse_evidence(entry, where, problems)) is not None
        ]
        questions.append(Question(id=qid, type=kind, question=text, evidence=tuple(evidence)))

    if not questions and not problems:
        problems.append("the golden set has no questions")
    if problems:
        raise ValueError("Invalid golden set:\n  " + "\n  ".join(problems))
    return int(raw.get("version") or 0), questions


def evidence_ranks(
    hits: list[dict[str, Any]], question: Question, stems: dict[str, str]
) -> list[int | None]:
    """Return, per evidence item, the 1-based rank of the first hit that is it, or None."""
    ranks: list[int | None] = []
    for item in question.evidence:
        rank = None
        for position, hit in enumerate(hits, start=1):
            if item.matches(stems.get(str(hit["document_id"]), ""), hit.get("chunk_raw")):
                rank = position
                break
        ranks.append(rank)
    return ranks


def first_rank(ranks: list[int | None]) -> int | None:
    """Return the rank of the first relevant chunk, or None when nothing was found."""
    found = [rank for rank in ranks if rank is not None]
    return min(found) if found else None


def recall_at(ranks: list[int | None], k: int) -> float:
    """Return the share of evidence items found within the top ``k``."""
    if not ranks:
        return 0.0
    return sum(1 for rank in ranks if rank is not None and rank <= k) / len(ranks)


def reciprocal_rank(ranks: list[int | None]) -> float:
    """Return 1/rank of the first relevant chunk, 0 when nothing was found."""
    rank = first_rank(ranks)
    return 1.0 / rank if rank else 0.0


def summarize(
    rows: list[dict[str, Any]], modes: tuple[str, ...], cutoffs: tuple[int, ...] = CUTOFFS
) -> dict[str, dict[str, dict[str, float]]]:
    """Average the metrics per mode, over every question with an answer and per type.

    Negative questions are left out: there is nothing for them to recall.
    """
    positives = [row for row in rows if not row["negative"]]
    groups: dict[str, list[dict[str, Any]]] = {"all": positives}
    for kind in QUESTION_TYPES:
        members = [row for row in positives if row["type"] == kind]
        if members:
            groups[kind] = members

    summary: dict[str, dict[str, dict[str, float]]] = {}
    for label, members in groups.items():
        if not members:
            continue
        summary[label] = {}
        for mode in modes:
            ranks = [row["modes"][mode]["ranks"] for row in members]
            entry: dict[str, float] = {"questions": len(members)}
            for k in cutoffs:
                entry[f"recall@{k}"] = fmean(recall_at(item, k) for item in ranks)
            entry["mrr"] = fmean(reciprocal_rank(item) for item in ranks)
            entry["missed"] = sum(1 for item in ranks if first_rank(item) is None)
            summary[label][mode] = entry
    return summary


def load_stems(connection) -> dict[str, str]:
    """Map every document id to the source file stem the golden set names it by."""
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT id, source_file FROM public.documents")
        return {str(doc_id): _nfc(Path(source).stem) for doc_id, source in cursor.fetchall()}
    finally:
        cursor.close()


def search_modes(
    connection, text: str, modes: tuple[str, ...], depth: int, settings: Settings
) -> dict[str, list[dict[str, Any]]]:
    """Return the top ``depth`` hits of every requested mode for one question.

    Full text alone runs directly and makes no API call. Any mode that needs
    the vector branch goes through ``compare()``, which embeds once for all.
    """
    if modes == ("fts",):
        return {"fts": run_search(connection, text, "fts", Filters(), depth, settings).hits}
    results = compare(connection, text, Filters(), depth, settings)
    return {mode: results[mode].hits for mode in modes}


def evaluate_question(
    question: Question, hits_by_mode: dict[str, list[dict[str, Any]]], stems: dict[str, str]
) -> dict[str, Any]:
    """Score one question in every mode that ran."""
    row: dict[str, Any] = {
        "id": question.id,
        "type": question.type,
        "question": question.question,
        "negative": question.negative,
        "modes": {},
    }
    for mode, hits in hits_by_mode.items():
        ranks = evidence_ranks(hits, question, stems)
        best = hits[0].get(_SCORE_KEY[mode]) if hits else None
        row["modes"][mode] = {
            "ranks": ranks,
            "first": first_rank(ranks),
            "hits": len(hits),
            "top_score": float(best) if best is not None else None,
            "top": [[stems.get(str(hit["document_id"]), "?"), hit["chunk_index"]] for hit in hits[:5]],
        }
    return row


def check_golden(connection, questions: list[Question], stems: dict[str, str]) -> list[str]:
    """Verify every evidence item against the database; print what each one matches."""
    by_stem = {stem: doc_id for doc_id, stem in stems.items()}
    problems: list[str] = []
    print(f"\n{'otázka':<24}{'dokument':<44}{'chunků':>7}{'příloha':>9}  chunky")
    cursor = connection.cursor()
    try:
        for question in questions:
            if question.negative:
                print(f"{question.id:<24}{'(v korpusu bez odpovědi)':<44}")
                continue
            annex_total = 0
            for item in question.evidence:
                doc_id = by_stem.get(item.doc)
                if doc_id is None:
                    problems.append(f"{question.id}: document {item.doc!r} is not in the database")
                    continue
                cursor.execute(
                    "SELECT chunk_index, content_kind, chunk_raw FROM public.document_chunks"
                    " WHERE document_id = %s ORDER BY chunk_index",
                    [doc_id],
                )
                matched = [
                    (index, kind)
                    for index, kind, text in cursor.fetchall()
                    if any(contains_normalized(text, snippet) for snippet in item.contains)
                ]
                annex = sum(1 for _, kind in matched if kind == "annex")
                annex_total += annex
                listing = ", ".join(f"#{index}" for index, _ in matched[:6])
                if len(matched) > 6:
                    listing += ", …"
                print(f"{question.id:<24}{item.doc[:42]:<44}{len(matched):>7}{annex:>9}  {listing}")
                if not matched:
                    problems.append(
                        f"{question.id}: no chunk of {item.doc!r} contains any of {list(item.contains)!r}"
                    )
            if question.type == "annex" and annex_total == 0:
                problems.append(f"{question.id}: type annex, but no evidence lies in an annex chunk")
    finally:
        cursor.close()
    return problems


def _rank(value: int | None) -> str:
    return "–" if value is None else str(value)


def print_report(
    rows: list[dict[str, Any]],
    summary: dict[str, dict[str, dict[str, float]]],
    modes: tuple[str, ...],
    depth: int,
    cutoffs: tuple[int, ...],
) -> None:
    """Print the evaluation for a terminal."""
    positives = [row for row in rows if not row["negative"]]
    negatives = [row for row in rows if row["negative"]]
    print(f"\nZlatá sada: {len(positives)} otázek s odpovědí, {len(negatives)} bez odpovědi, hloubka {depth}")

    if "all" in summary:
        print()
        print(f"{'režim':<9}" + "".join(f"{'recall@' + str(k):>11}" for k in cutoffs) + f"{'MRR':>8}{'nenalezeno':>12}")
        for mode in modes:
            entry = summary["all"][mode]
            print(
                f"{mode:<9}"
                + "".join(f"{entry[f'recall@{k}']:>11.2f}" for k in cutoffs)
                + f"{entry['mrr']:>8.3f}{int(entry['missed']):>12}"
            )

        print("\nMRR podle typu otázky")
        print(f"{'typ':<12}{'otázek':>7}" + "".join(f"{mode:>9}" for mode in modes))
        for kind in QUESTION_TYPES:
            if kind in summary:
                entries = summary[kind]
                print(
                    f"{kind:<12}{int(entries[modes[0]]['questions']):>7}"
                    + "".join(f"{entries[mode]['mrr']:>9.3f}" for mode in modes)
                )

        print(f"\nPořadí prvního relevantního chunku (– = není v top {depth})")
        print(f"{'otázka':<24}{'typ':<12}" + "".join(f"{mode:>9}" for mode in modes))
        for row in positives:
            print(
                f"{row['id']:<24}{row['type']:<12}"
                + "".join(f"{_rank(row['modes'][mode]['first']):>9}" for mode in modes)
            )

    if negatives:
        print("\nOtázky bez odpovědi: co vyhledávání přesto vrátí (počet výsledků / skóre prvního)")
        print(f"{'otázka':<24}" + "".join(f"{mode:>20}" for mode in modes))
        for row in negatives:
            cells = []
            for mode in modes:
                data = row["modes"][mode]
                score = "–" if data["top_score"] is None else f"{data['top_score']:.3f}"
                cells.append(f"{data['hits']} / {score}")
            print(f"{row['id']:<24}" + "".join(f"{cell:>20}" for cell in cells))
    print()


def write_results(path: Path, payload: dict[str, Any]) -> None:
    """Write the evaluation as JSON for later comparison."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def select_questions(
    questions: list[Question], only: list[str] | None, types: list[str] | None
) -> list[Question]:
    """Restrict the set to the requested ids and types.

    Raises:
        ValueError: When ``only`` names an id the set does not have.
    """
    if only:
        unknown = sorted(set(only) - {question.id for question in questions})
        if unknown:
            raise ValueError(f"Unknown question ids: {', '.join(unknown)}")
        questions = [question for question in questions if question.id in set(only)]
    if types:
        questions = [question for question in questions if question.type in set(types)]
    return questions


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Measure retrieval quality against the golden set.")
    parser.add_argument("--check", action="store_true", help="Verify the golden set against the database; no API call")
    parser.add_argument("--only", nargs="+", metavar="ID", help="Evaluate only these question ids")
    parser.add_argument("--type", nargs="+", choices=QUESTION_TYPES, dest="types", help="Evaluate only these question types")
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES), help="Search modes (default: all)")
    parser.add_argument("--depth", type=int, default=DEPTH, help=f"Ranks examined per mode (default: {DEPTH})")
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH, help="Golden set file")
    parser.add_argument("--out", type=Path, help="JSON results file (default: processed/eval/retrieval-<time>.json)")
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
    if args.depth < 1:
        logger.error("--depth must be at least 1")
        return 1

    modes = tuple(mode for mode in MODES if mode in args.modes)
    cutoffs = tuple(sorted({k for k in CUTOFFS if k < args.depth} | {args.depth}))
    settings = load_settings()

    connection = psycopg2.connect(**load_connection_params())
    try:
        stems = load_stems(connection)
        if args.check:
            problems = check_golden(connection, questions, stems)
            if problems:
                print("Problémy:\n  " + "\n  ".join(problems) + "\n")
                return 1
            print(f"\nZlatá sada v{version} odpovídá databázi: {len(questions)} otázek.\n")
            return 0

        rows: list[dict[str, Any]] = []
        for number, question in enumerate(questions, start=1):
            logger.info("[%d/%d] %s", number, len(questions), question.id)
            try:
                hits_by_mode = search_modes(connection, question.question, modes, args.depth, settings)
            except EmbeddingUnavailable as exc:
                logger.error(
                    "Could not embed %r (%s). Full text alone needs no API: re-run with --modes fts.",
                    question.id,
                    exc,
                )
                return 1
            rows.append(evaluate_question(question, hits_by_mode, stems))
    finally:
        connection.close()

    summary = summarize(rows, modes, cutoffs)
    print_report(rows, summary, modes, args.depth, cutoffs)

    if not args.no_save:
        path = args.out or RESULTS_DIR / f"retrieval-{datetime.now():%Y%m%d-%H%M%S}.json"
        write_results(
            path,
            {
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "golden": {"path": str(args.golden), "version": version, "questions": len(questions)},
                "depth": args.depth,
                "modes": list(modes),
                "embedding_model": settings.embedding_model,
                "embedding_dimensions": settings.embedding_dimensions,
                "summary": summary,
                "questions": rows,
            },
        )
        print(f"Výsledky: {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
