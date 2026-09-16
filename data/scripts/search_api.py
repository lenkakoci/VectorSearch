"""HTTP API over the search and answering services, for the web demo.

A thin FastAPI layer: every endpoint validates its input with a Pydantic model,
opens one connection, calls the service and returns what it got. No search or
answering logic lives here, so the command line and the web see the same
results.

    GET  /api/health                                     corpus counts
    GET  /api/facets                                     values every filter can take
    POST /api/search                                     one mode, ``rerank`` included
    POST /api/compare                                    fts, vector and hybrid side by side,
                                                         and reranking when ``rerank`` is set
    POST /api/answer                                     a grounded answer with checked citations
    POST /api/answer/stream                              the same answer, with progress as it happens
    GET  /api/chunks/{document_id}/{chunk_index}/context the chunks around a hit
    GET  /api/documents/{document_id}                    one report with its extraction
    GET  /api/documents/{document_id}/pdf                the source PDF, so a citation can open its page

Reranking calls Gemini for every candidate not graded before, so
``/api/compare`` runs it only on request. A reranking failure there leaves the
other columns intact and reports ``rerank_error`` in the rerank column's debug;
``/api/search`` with mode ``rerank`` answers 503 instead.

``/api/answer`` never invents: when no candidate reaches the relevance gate it
returns status ``no_evidence`` with the nearest candidates and calls no model.

Inline prefixes in the query (``autor:Poul hladina vody``) work exactly as on
the command line and win over the structured filters, so a demo can show both.

Run from data/scripts:
    uv run uvicorn search_api:app --reload --port 8010
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any, Literal

import psycopg2
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

import answer_log
from answer_service import AnswerResult, AnswerUnavailable, answer
from context_builder import MAX_SOURCES, PER_DOCUMENT, TOKEN_BUDGET
from pathlib import Path

from pipeline_common import ANSWERS_DIR, configure_logging, load_connection_params, load_settings
from rerank_service import MAX_GRADE, MIN_GRADE, RerankUnavailable
from search_filters import Filters, build_filters, parse_query
from search_service import (
    CANDIDATES,
    MODES,
    RERANK_MODE,
    EmbeddingUnavailable,
    SearchResult,
    compare,
    corpus_counts,
    facets,
    get_document,
    neighbours,
    run_search,
)

logger = logging.getLogger(__name__)

Mode = Literal["fts", "vector", "hybrid", "rerank"]
ContentKind = Literal["prose", "annex"]
AnswerStatus = Literal["answered", "partial", "insufficient", "no_evidence"]

_DEFAULT_ORIGINS = "http://localhost:5173,http://localhost:3001"


class FiltersIn(BaseModel):
    """Structured metadata restrictions, as the web form sends them.

    Text fields are lists so a multi-select maps onto them directly; dates take
    ``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD`` and widen to the edge of the period.
    """

    authors: list[str] = []
    organizations: list[str] = []
    municipalities: list[str] = []
    clients: list[str] = []
    report_types: list[str] = []
    locality: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    document_ids: list[str] = []
    content_kind: ContentKind | None = None

    def to_filters(self) -> Filters:
        """Convert to the search vocabulary."""
        return build_filters(
            author=self.authors,
            organization=self.organizations,
            municipality=self.municipalities,
            client=self.clients,
            report_type=self.report_types,
            locality=self.locality,
            date_from=self.date_from,
            date_to=self.date_to,
            document_ids=self.document_ids,
            content_kind=self.content_kind,
        )


class QueryIn(BaseModel):
    """A query with its limit and filters."""

    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(10, ge=1, le=50)
    filters: FiltersIn = FiltersIn()


class SearchRequest(QueryIn):
    """A query to run in one mode."""

    mode: Mode = "hybrid"


class CompareRequest(QueryIn):
    """A query to run in every mode."""

    rerank: bool = Field(False, description="Also grade forty hybrid candidates with Gemini; costs API calls")


class AnswerOptions(BaseModel):
    """How much evidence the answer may use, and how strict the gate is."""

    candidates: int = Field(CANDIDATES, ge=5, le=80)
    min_grade: int = Field(MIN_GRADE, ge=0, le=MAX_GRADE)
    max_sources: int = Field(MAX_SOURCES, ge=1, le=20)
    per_document: int = Field(PER_DOCUMENT, ge=1, le=20)
    token_budget: int = Field(TOKEN_BUDGET, ge=500, le=60000)
    neighbours: bool = True
    trace: bool = Field(True, description="Return the prompt and the raw answer in the trace")
    fresh: bool = Field(False, description="Answer again instead of returning the stored answer")


class AnswerRequest(BaseModel):
    """A question to answer from the corpus."""

    question: str = Field(min_length=1, max_length=1000)
    filters: FiltersIn = FiltersIn()
    options: AnswerOptions = AnswerOptions()


class Hit(BaseModel):
    """One chunk in a ranking, with everything needed to say why it is there."""

    chunk_id: str
    document_id: str
    chunk_index: int
    section: str | None
    content_kind: str
    page_from: int | None
    page_to: int | None
    chunk_raw: str
    snippet: str
    headline: str | None
    lexical_match: bool
    title: str | None
    author: str | None
    organization: str | None
    municipality: str | None
    report_type: str | None
    report_date: date | None
    locality: str | None
    token_count: int | None = None
    vector_rank: int | None
    vector_score: float | None
    fts_rank: int | None
    fts_score: float | None
    rrf_score: float | None
    candidate_rank: int | None = None
    rerank_grade: int | None = None
    rerank_reason: str | None = None


class SearchResponse(BaseModel):
    """One ranking plus its diagnostics."""

    query: str
    mode: Mode
    limit: int
    fetch: int
    hits: list[Hit]
    debug: dict[str, Any]


class CompareResponse(BaseModel):
    """The same query in every mode; ``rerank`` only when it was requested."""

    query: str
    fts: SearchResponse
    vector: SearchResponse
    hybrid: SearchResponse
    rerank: SearchResponse | None = None


class CheckedStatement(BaseModel):
    """One sentence of the answer and the verdict of the citation check."""

    text: str
    source_ids: list[int]
    quotes: list[str]
    check: str
    note: str


class AnswerConflict(BaseModel):
    """Two sources saying different things about the same thing."""

    topic: str
    source_ids: list[int]
    description: str


class AnswerSource(BaseModel):
    """One chunk offered to the model, with its place in the answer."""

    id: int
    role: str
    cited: bool = False
    chunk_id: str
    document_id: str
    chunk_index: int
    section: str | None
    content_kind: str
    page_from: int | None
    page_to: int | None
    chunk_raw: str
    title: str | None
    municipality: str | None
    report_type: str | None
    report_date: date | None
    organization: str | None
    token_count: int | None = None
    rerank_grade: int | None = None
    rerank_reason: str | None = None
    candidate_rank: int | None = None


class AnswerResponse(BaseModel):
    """A grounded answer: sentences, their sources and how it was produced."""

    question: str
    status: AnswerStatus
    statements: list[CheckedStatement]
    missing: list[str]
    conflicts: list[AnswerConflict]
    sources: list[AnswerSource]
    model: str
    prompt_version: int
    trace: dict[str, Any]


class FacetValue(BaseModel):
    value: str
    count: int


class ContentKindCount(BaseModel):
    value: str
    count: int
    with_vector: int


class DocumentSummary(BaseModel):
    id: str
    title: str | None
    author: str | None
    report_date: date | None
    report_type: str | None
    locality: str | None
    municipality: str | None
    organization: str | None
    chunks: int
    chunks_with_vector: int


class FacetsResponse(BaseModel):
    """What every filter can take, keyed by filter name."""

    author: list[FacetValue]
    organization: list[FacetValue]
    municipality: list[FacetValue]
    client: list[FacetValue]
    report_type: list[FacetValue]
    years: dict[str, int | None]
    content_kinds: list[ContentKindCount]
    documents: list[DocumentSummary]


class ContextChunk(BaseModel):
    chunk_id: str | None = None
    token_count: int | None = None
    chunk_index: int
    section: str | None
    content_kind: str
    page_from: int | None
    page_to: int | None
    chunk_raw: str
    is_hit: bool


class ContextResponse(BaseModel):
    document_id: str
    title: str | None
    chunks: list[ContextChunk]


class DocumentResponse(BaseModel):
    id: str
    source_file: str
    title: str | None
    report_type: str | None
    locality: str | None
    report_date: date | None
    author: str | None
    client: str | None
    summary: str | None
    extraction: dict[str, Any]
    extraction_model: str | None
    extraction_schema_version: int
    chunks: int


class HealthResponse(BaseModel):
    status: str
    documents: int
    chunks: int
    chunks_with_vector: int


@contextmanager
def connection() -> Iterator[Any]:
    """Open one database connection for the duration of a request."""
    conn = psycopg2.connect(**load_connection_params())
    try:
        yield conn
    finally:
        conn.close()


def _resolve(text: str, filters: FiltersIn) -> tuple[str, Filters]:
    """Split inline prefixes off the text and merge them with the form filters."""
    remaining, inline = parse_query(text)
    if not remaining:
        raise HTTPException(status_code=422, detail="Dotaz neobsahuje žádný hledaný text, jen filtry.")
    return remaining, inline.merge(filters.to_filters())


def _response(result: SearchResult) -> SearchResponse:
    return SearchResponse(
        query=result.query,
        mode=result.mode,  # type: ignore[arg-type]
        limit=result.limit,
        fetch=result.fetch,
        hits=[Hit.model_validate(hit) for hit in result.hits],
        debug=result.debug,
    )


def _answer_response(result: AnswerResult) -> AnswerResponse:
    return AnswerResponse(
        question=result.question,
        status=result.status,  # type: ignore[arg-type]
        statements=[CheckedStatement.model_validate(statement) for statement in result.statements],
        missing=result.missing,
        conflicts=[AnswerConflict.model_validate(conflict) for conflict in result.conflicts],
        sources=[AnswerSource.model_validate(source) for source in result.sources],
        model=result.model,
        prompt_version=result.prompt_version,
        trace=result.trace,
    )


def _embedding_error(exc: EmbeddingUnavailable) -> HTTPException:
    logger.error("Embedding unavailable: %s", exc)
    return HTTPException(
        status_code=503,
        detail="Embedding dotazu není dostupný (chybí klíč nebo je vyčerpaná kvóta). "
        "Fulltextový režim funguje bez něj.",
    )


def _rerank_error(exc: RerankUnavailable) -> HTTPException:
    logger.error("Reranking unavailable: %s", exc)
    return HTTPException(
        status_code=503,
        detail="Reranking není dostupný (model neodpověděl nebo chybí klíč). "
        "Hybridní režim funguje bez něj.",
    )


def _answer_error(exc: AnswerUnavailable) -> HTTPException:
    logger.error("Answering unavailable: %s", exc)
    return HTTPException(
        status_code=503,
        detail="Model pro odpověď není dostupný. Vyhledávání funguje bez něj.",
    )


def _parse_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{value!r} není UUID dokumentu") from exc


router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report whether the database answers and how much it holds."""
    try:
        with connection() as conn:
            counts = corpus_counts(conn)
    except psycopg2.Error as exc:
        raise HTTPException(status_code=503, detail=f"Databáze neodpovídá: {exc}") from exc
    return HealthResponse(status="ok", **counts)


@router.get("/facets", response_model=FacetsResponse)
def get_facets() -> FacetsResponse:
    """Return the values every filter can take, with counts."""
    with connection() as conn:
        return FacetsResponse.model_validate(facets(conn))


@router.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    """Search in one mode."""
    text, filters = _resolve(request.query, request.filters)
    try:
        with connection() as conn:
            result = run_search(conn, text, request.mode, filters, request.limit, SETTINGS)
    except EmbeddingUnavailable as exc:
        raise _embedding_error(exc) from exc
    except RerankUnavailable as exc:
        raise _rerank_error(exc) from exc
    return _response(result)


@router.post("/compare", response_model=CompareResponse)
def compare_modes(request: CompareRequest) -> CompareResponse:
    """Run the query in every mode; one embedding request serves them all."""
    text, filters = _resolve(request.query, request.filters)
    modes = MODES + ((RERANK_MODE,) if request.rerank else ())
    try:
        with connection() as conn:
            results = compare(conn, text, filters, request.limit, SETTINGS, modes=modes)
    except EmbeddingUnavailable as exc:
        raise _embedding_error(exc) from exc
    return CompareResponse(query=text, **{mode: _response(result) for mode, result in results.items()})


@router.post("/answer", response_model=AnswerResponse)
def answer_question(request: AnswerRequest) -> AnswerResponse:
    """Answer a question from the corpus, with every sentence checked."""
    text, filters = _resolve(request.question, request.filters)
    options = request.options
    try:
        with connection() as conn:
            result = answer(
                conn,
                text,
                filters,
                settings=SETTINGS,
                candidates=options.candidates,
                min_grade=options.min_grade,
                max_sources=options.max_sources,
                per_document=options.per_document,
                token_budget=options.token_budget,
                use_neighbours=options.neighbours,
                keep_prompt=options.trace,
                cache_dir=ANSWERS_DIR,
                fresh=options.fresh,
            )
    except EmbeddingUnavailable as exc:
        raise _embedding_error(exc) from exc
    except RerankUnavailable as exc:
        raise _rerank_error(exc) from exc
    except AnswerUnavailable as exc:
        raise _answer_error(exc) from exc
    answer_log.append(
        answer_log.record(
            result,
            source="api",
            filters=filters.as_dict(),
            options=options.model_dump(exclude_defaults=True),
        )
    )
    return _answer_response(result)


def _sse(event: str, payload: dict[str, Any]) -> str:
    """Format one server-sent event: a named event and one line of JSON."""
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {data}\n\n"


@router.post("/answer/stream")
def answer_question_streamed(request: AnswerRequest) -> StreamingResponse:
    """Answer a question and report every step while it happens.

    The same chain as ``POST /api/answer``, and the same final payload, sent as
    the ``answer`` event. What it adds is the waiting: grading forty candidates
    and writing the answer take ten to thirty seconds, and a page that says
    which of those is running now is a different experience from one spinner.

    The chain is synchronous, so it runs in a thread and pushes its steps into
    a queue that this generator drains. A client that disappears mid-answer
    leaves the thread to finish and be garbage collected; nothing is written
    twice, because the log and the cache are written inside the chain's own
    call.
    """
    text, filters = _resolve(request.question, request.filters)
    options = request.options
    events: queue.Queue = queue.Queue()

    def work() -> None:
        try:
            with connection() as conn:
                result = answer(
                    conn,
                    text,
                    filters,
                    settings=SETTINGS,
                    candidates=options.candidates,
                    min_grade=options.min_grade,
                    max_sources=options.max_sources,
                    per_document=options.per_document,
                    token_budget=options.token_budget,
                    use_neighbours=options.neighbours,
                    keep_prompt=options.trace,
                    cache_dir=ANSWERS_DIR,
                    fresh=options.fresh,
                    on_progress=lambda step, payload: events.put(("progress", {"step": step, **payload})),
                )
            answer_log.append(
                answer_log.record(
                    result,
                    source="api",
                    filters=filters.as_dict(),
                    options=options.model_dump(exclude_defaults=True),
                )
            )
            events.put(("answer", _answer_response(result).model_dump(mode="json")))
        except (EmbeddingUnavailable, RerankUnavailable, AnswerUnavailable) as exc:
            events.put(("error", {"detail": str(exc), "kind": type(exc).__name__}))
        except Exception as exc:  # noqa: BLE001 - the stream must say something and end
            logger.exception("Odpověď ve streamu selhala")
            events.put(("error", {"detail": str(exc), "kind": type(exc).__name__}))
        finally:
            events.put(None)

    def stream() -> Iterator[str]:
        thread = threading.Thread(target=work, name="answer-stream", daemon=True)
        thread.start()
        while True:
            item = events.get()
            if item is None:
                return
            name, payload = item
            yield _sse(name, payload)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # nginx buffers a proxied response by default, which would hold
            # every step until the answer is finished and defeat the point.
            "X-Accel-Buffering": "no",
        },
    )


def source_pdf(name: str | None) -> Path | None:
    """Return the PDF a document was made from, or None when it is not there.

    Only the file name from the database is used and it is resolved inside the
    configured input directory, so a crafted ``source_file`` cannot reach out
    of it. A corpus built from Markdown, or one whose PDFs live elsewhere than
    this machine, simply has no file to serve.
    """
    if not name:
        return None
    root = SETTINGS.input_dir.resolve()
    candidate = (root / Path(str(name)).name).resolve()
    if candidate.parent != root or candidate.suffix.lower() != ".pdf" or not candidate.is_file():
        return None
    return candidate


@router.get("/documents/{document_id}/pdf")
def document_pdf(document_id: str) -> FileResponse:
    """Serve the source PDF inline, so a citation can open the page it names.

    The browser's own viewer honours ``#page=N``, so the page number a chunk
    carries becomes a link rather than an instruction to scroll.
    """
    document_id = _parse_uuid(document_id)
    with connection() as conn:
        document = get_document(conn, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokument neexistuje")
    path = source_pdf(document.get("source_file"))
    if path is None:
        raise HTTPException(status_code=404, detail="Zdrojové PDF není k dispozici")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        content_disposition_type="inline",
    )


@router.get("/chunks/{document_id}/{chunk_index}/context", response_model=ContextResponse)
def chunk_context(
    document_id: str,
    chunk_index: int,
    before: int = Query(1, ge=0, le=5),
    after: int = Query(1, ge=0, le=5),
) -> ContextResponse:
    """Return the chunks around one chunk, in reading order."""
    document_id = _parse_uuid(document_id)
    with connection() as conn:
        document = get_document(conn, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Dokument nenalezen")
        chunks = neighbours(conn, document_id, chunk_index, before, after)
    if not any(chunk["is_hit"] for chunk in chunks):
        raise HTTPException(status_code=404, detail="Chunk nenalezen")
    return ContextResponse(document_id=document_id, title=document.get("title"), chunks=chunks)


@router.get("/documents/{document_id}", response_model=DocumentResponse)
def document_detail(document_id: str) -> DocumentResponse:
    """Return one report with its full extraction."""
    document_id = _parse_uuid(document_id)
    with connection() as conn:
        document = get_document(conn, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokument nenalezen")
    document["extraction"] = document.pop("extraction_json") or {}
    return DocumentResponse.model_validate(document)


def create_app() -> FastAPI:
    """Build the application."""
    configure_logging()
    origins = [item.strip() for item in os.getenv("CORS_ORIGINS", _DEFAULT_ORIGINS).split(",") if item.strip()]
    application = FastAPI(title="VectorSearch demo API", version="0.3.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(router)
    return application


SETTINGS = load_settings()
app = create_app()
