"""Answer a question from the reports, with every sentence tied to a source.

The chain: hybrid retrieval with the any-word full text, reranking by grade,
the relevance gate, context building, one model call, and a deterministic
check of what came back. Every step leaves its numbers in the trace, so a demo
can show where search ends and generation begins.

Nothing is answered without evidence. When no candidate reaches the gate the
model is not called at all: the result is ``no_evidence`` with the best
candidates attached, which is both the honest answer and the cheap one.

Statuses the caller sees:

    answered      every sentence carries a quote that was found in its source
    partial       the model answered part of it, or a sentence failed a check
    insufficient  the sources do not answer the question
    no_evidence   nothing reached the relevance gate; the model never ran

The command line (``ask_reports.py``) and the API (``search_api.py``) both
call ``answer()``, so they cannot drift apart. Costs per question: one query
embedding, up to two grading calls for candidates not graded before, and one
answering call.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from collections.abc import Callable
from typing import Any

from google.genai import types
from pydantic import ValidationError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

import answer_cache
from answer_prompts import ANSWER_INSTRUCTIONS, PROMPT_VERSION, GroundedAnswer
from citation_check import check_answer, final_status
from context_builder import (
    MAX_NEIGHBOURS,
    MAX_SOURCES,
    PER_DOCUMENT,
    TOKEN_BUDGET,
    build_context,
    reaches_gate,
)
from gemini_auth import create_gemini_client, is_retryable_error
from pipeline_common import Settings, load_settings
from rerank_service import MIN_GRADE, Reranker
from search_filters import Filters
from search_service import CANDIDATES, RERANK_MODE, SearchResult, compare, neighbours

logger = logging.getLogger(__name__)

NO_EVIDENCE = "no_evidence"

# The steps ``on_progress`` reports, in the order they happen. A question that
# is cached reports "cache" and nothing else; one that fails the gate stops
# after "gate".
PROGRESS_STEPS = ("start", "cache", "retrieval", "gate", "context", "generation", "validation")
BELOW_GATE_ROLE = "pod prahem"
FALLBACK_SOURCES = 5


class AnswerUnavailable(RuntimeError):
    """The answering model could not be reached or answered unusably."""


@dataclass
class AnswerResult:
    """One answered question: the sentences, their sources and how it was produced."""

    question: str
    status: str
    statements: list[dict[str, Any]]
    missing: list[str]
    conflicts: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    model: str
    prompt_version: int
    trace: dict[str, Any] = field(default_factory=dict)


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception(is_retryable_error),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def call_model(model: str, prompt: str) -> GroundedAnswer:
    """Ask the model for a grounded answer.

    Raises:
        ValueError: When the answer is not the requested JSON.
    """
    client = create_gemini_client()
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=ANSWER_INSTRUCTIONS,
            response_mime_type="application/json",
            response_schema=GroundedAnswer,
            # An answer must be reproducible, not creative.
            temperature=0.0,
            # No tools are offered; left on, the SDK warns on every call.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    parsed = response.parsed
    if isinstance(parsed, GroundedAnswer):
        return parsed
    try:
        return GroundedAnswer.model_validate_json(response.text or "")
    except ValidationError as exc:
        raise ValueError(f"Model returned unparsable output: {(response.text or '')[:200]!r}") from exc


def _fallback_sources(hits: list[dict[str, Any]], count: int = FALLBACK_SOURCES) -> list[dict[str, Any]]:
    """Return the best candidates that did not reach the gate, for the user to judge."""
    sources = []
    for number, hit in enumerate(hits[:count], start=1):
        source = dict(hit)
        source["id"] = number
        source["role"] = BELOW_GATE_ROLE
        source["cited"] = False
        sources.append(source)
    return sources


def _retrieval_trace(search: SearchResult) -> dict[str, Any]:
    """Keep the parts of the search debug that explain the answer."""
    wanted = (
        "fetch",
        "filters",
        "filter_sql",
        "query_words",
        "tsquery",
        "embed_ms",
        "embedding_cached",
        "vector_ms",
        "vector_candidates",
        "fts_any_ms",
        "fts_any_candidates",
    )
    return {key: search.debug[key] for key in wanted if key in search.debug}


def _reporter(on_progress: Callable[[str, dict[str, Any]], None] | None):
    """Return a function that reports one step, swallowing callback failures.

    The caller of an answer is usually a stream that can drop; that must cost
    the progress line, never the answer.
    """

    def report(step: str, **payload: Any) -> None:
        if on_progress is None:
            return
        try:
            on_progress(step, payload)
        except Exception:  # noqa: BLE001 - a broken listener is not an error here
            logger.debug("Posluchač průběhu selhal na kroku %s", step, exc_info=True)

    return report


def _from_cache(payload: dict[str, Any], *, keep_prompt: bool) -> AnswerResult | None:
    """Rebuild an answer stored earlier; None when the payload is unusable.

    A cache that cannot be read is a miss, never an error: the chain can always
    produce the answer again.
    """
    try:
        trace = dict(payload.get("trace") or {})
        trace["cache"] = "hit"
        if not keep_prompt:
            trace.pop("prompt", None)
            trace.pop("raw_answer", None)
        return AnswerResult(
            question=payload["question"],
            status=payload["status"],
            statements=payload["statements"],
            missing=payload["missing"],
            conflicts=payload["conflicts"],
            sources=payload["sources"],
            model=payload["model"],
            prompt_version=payload["prompt_version"],
            trace=trace,
        )
    except (KeyError, TypeError) as exc:
        logger.warning("Uložená odpověď má neznámý tvar (%s), počítá se znovu", exc)
        return None


def answer(
    connection,
    question: str,
    filters: Filters | None = None,
    *,
    settings: Settings | None = None,
    reranker: Reranker | None = None,
    candidates: int = CANDIDATES,
    min_grade: int = MIN_GRADE,
    max_sources: int = MAX_SOURCES,
    token_budget: int = TOKEN_BUDGET,
    per_document: int = PER_DOCUMENT,
    max_neighbours: int = MAX_NEIGHBOURS,
    use_neighbours: bool = True,
    keep_prompt: bool = True,
    cache_dir: Path | None = None,
    fresh: bool = False,
    on_progress: Callable[[str, dict[str, Any]], None] | None = None,
) -> AnswerResult:
    """Answer one question from the corpus.

    With ``cache_dir`` set, an identical question answered before is returned
    from disk without calling any model, and a fresh answer is stored there.
    The key covers the filters, the options, the model, the prompt version and
    a fingerprint of the corpus, so nothing that would change the answer is
    ignored. ``fresh`` skips reading what is stored and replaces it, which is
    how a demo asks for the model to be run again.

    ``on_progress`` is called with a step name and its numbers as the chain
    moves, so a caller can show where an answer is rather than one spinner for
    the whole half-minute. The steps are in ``PROGRESS_STEPS``; a failure
    inside the callback never stops the answer.

    Raises:
        ValueError: On an empty question.
        EmbeddingUnavailable: When the query cannot be embedded.
        RerankUnavailable: When the candidates cannot be graded.
        AnswerUnavailable: When the answering model cannot be reached.
    """
    question = " ".join(question.split())
    if not question:
        raise ValueError("Nothing to ask")
    settings = settings or load_settings()
    filters = filters or Filters()
    started = time.perf_counter()
    report = _reporter(on_progress)
    report("start", question=question, candidates=candidates)

    cache_key: str | None = None
    if cache_dir is not None:
        cache_key = answer_cache.key_of(
            question,
            filters=filters.as_dict(),
            options={
                "candidates": candidates,
                "min_grade": min_grade,
                "max_sources": max_sources,
                "token_budget": token_budget,
                "per_document": per_document,
                "max_neighbours": max_neighbours,
                "neighbours": use_neighbours,
            },
            model=settings.answer_model,
            prompt_version=PROMPT_VERSION,
        )
        stored = None if fresh else answer_cache.load(cache_key, cache_dir)
        if stored is not None:
            cached = _from_cache(stored, keep_prompt=keep_prompt)
            if cached is not None:
                logger.info("Odpověď na %r je z cache, model se nevolá", question)
                report("cache", hit=True, status=cached.status, statements=len(cached.statements))
                return cached

    search = compare(
        connection,
        question,
        filters or Filters(),
        candidates,
        settings,
        modes=(RERANK_MODE,),
        reranker=reranker,
        raise_rerank_errors=True,
    )[RERANK_MODE]
    hits = search.hits
    passed = [hit for hit in hits if reaches_gate(hit, min_grade)]

    trace: dict[str, Any] = {
        "retrieval": _retrieval_trace(search),
        "rerank": search.debug.get("rerank"),
        "gate": {"min_grade": min_grade, "candidates": len(hits), "passed": len(passed)},
    }
    rerank_stats = search.debug.get("rerank") or {}
    report(
        "retrieval",
        candidates=len(hits),
        graded=rerank_stats.get("graded"),
        cached=rerank_stats.get("cached"),
        ms=rerank_stats.get("ms"),
    )
    report("gate", passed=len(passed), candidates=len(hits), min_grade=min_grade)

    if not passed:
        logger.info("Gate closed for %r: no candidate reached grade %d", question, min_grade)
        trace["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return _remember(cache_key, cache_dir, AnswerResult(
            question=question,
            status=NO_EVIDENCE,
            statements=[],
            missing=[],
            conflicts=[],
            sources=_fallback_sources(hits),
            model=settings.answer_model,
            prompt_version=PROMPT_VERSION,
            trace=trace,
        ))

    fetch = None
    if use_neighbours:
        def fetch(document_id: str, chunk_index: int) -> list[dict[str, Any]]:
            return neighbours(connection, document_id, chunk_index, 1, 1)

    context = build_context(
        question,
        hits,
        fetch,
        min_grade=min_grade,
        max_sources=max_sources,
        token_budget=token_budget,
        per_document=per_document,
        max_neighbours=max_neighbours,
    )
    trace["context"] = context.stats
    report(
        "context",
        sources=context.stats.get("sources"),
        tokens=context.stats.get("tokens"),
        neighbours=context.stats.get("neighbours"),
        documents=context.stats.get("documents"),
    )

    report("generation", model=settings.answer_model)
    started_model = time.perf_counter()
    try:
        raw = call_model(settings.answer_model, context.prompt)
    except Exception as exc:  # noqa: BLE001 - every cause has the same remedy
        raise AnswerUnavailable(f"{type(exc).__name__}: {exc}") from exc
    generation_ms = round((time.perf_counter() - started_model) * 1000, 1)

    statements, summary = check_answer(
        [statement.model_dump() for statement in raw.statements], context.sources
    )
    status = final_status(raw.status, statements)
    known = {int(source["id"]) for source in context.sources}
    conflicts = [
        {**conflict.model_dump(), "source_ids": [value for value in conflict.source_ids if value in known]}
        for conflict in raw.conflicts
    ]

    cited = set(summary["cited_sources"])
    sources = [{**source, "cited": int(source["id"]) in cited} for source in context.sources]

    trace["generation"] = {
        "model": settings.answer_model,
        "prompt_version": PROMPT_VERSION,
        "ms": generation_ms,
        "model_status": raw.status,
    }
    trace["validation"] = summary
    trace["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
    report(
        "validation",
        statements=summary["statements"],
        verified=summary["verified"],
        status=status,
        ms=generation_ms,
    )
    if keep_prompt:
        trace["prompt"] = context.prompt
        trace["raw_answer"] = raw.model_dump()

    return _remember(
        cache_key,
        cache_dir,
        AnswerResult(
            question=question,
            status=status,
            statements=statements,
            missing=[str(item) for item in raw.missing],
            conflicts=conflicts,
            sources=sources,
            model=settings.answer_model,
            prompt_version=PROMPT_VERSION,
            trace=trace,
        ),
    )


def _remember(key: str | None, directory: Path | None, result: AnswerResult) -> AnswerResult:
    """Store an answer for the next identical question, and return it unchanged."""
    if key and directory is not None:
        answer_cache.store(key, asdict(result), directory)
    return result
