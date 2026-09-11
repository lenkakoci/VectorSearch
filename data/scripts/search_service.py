"""Search over the imported reports, as a library.

The command line (``search_reports.py``) and the HTTP API (``search_api.py``)
both go through this module, so every query exists once. Nothing here prints,
parses arguments or opens a connection: every function takes an open psycopg2
connection and returns plain dicts, which suits a terminal renderer and a JSON
serialiser equally.

Three modes:

- ``vector``: embed the query, rank by cosine distance over the HNSW index.
- ``fts``: full text only. Makes **no API call at all**, so it costs nothing, is
  not subject to the embedding quota, and works without a Gemini key.
- ``hybrid``: run both and merge the rankings with Reciprocal Rank Fusion. Vector
  search is weak at exact tokens - borehole ids like V-3, parcel numbers,
  standard references - and full text is weak at paraphrase. RRF needs no score
  normalisation between the two.

``compare()`` runs the two branches once and derives all three rankings from
them - one embedding request, two SQL queries, three views. It exists for the
demo that puts the modes side by side.

Every hit carries the rank and score it had in each branch that ran
(``vector_rank``/``vector_score``, ``fts_rank``/``fts_score``) and the fused
``rrf_score``, so a result can say why it was found. Earlier the fusion kept
only the score of whichever branch saw the chunk first, and that information was
lost.

Two things are computed in SQL rather than in Python because PostgreSQL knows
the Czech dictionary and Python does not:

- ``lexical_match``: whether the chunk contains the query's words at all, under
  the same two configurations the full-text branch searches with. A vector hit
  with ``lexical_match = false`` was found by meaning alone.
- ``headline``: ``ts_headline`` fragments with the matching words wrapped in
  ``<mark>``, which highlights an inflected form (``vrtů`` for the query
  ``vrty``) - exactly what a Python substring search would miss.

Both are computed only for the rows that survive ``LIMIT``, in an outer query
around the ranking, because ``ts_headline`` re-parses the chunk with the
dictionary and is not cheap enough to run on every candidate.

The metadata filter is SQL from ``search_filters.py``: both branches are already
SQL, so a restriction is just more ``WHERE``.

The full-text side asks both Czech configurations from
sql/tables/03_create_czech_fts.sql: ``czech`` matches across inflection, and
``czech_literal`` matches a query typed without diacritics. Chunks are indexed
under both, so OR-ing the two queries finds whatever either one would.

``websearch_to_tsquery`` rather than ``plainto_tsquery``: it understands quoted
phrases, ``or`` and ``-word``, and unlike ``to_tsquery`` it never raises on
whatever the user types. Terms are still ANDed by default, which only became
workable once the dictionary made inflected forms meet and dropped stop words.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from google.genai import types
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from gemini_auth import create_gemini_client, is_retryable_error, normalize
from pipeline_common import Settings, load_settings
from search_filters import Filters, column_expression

logger = logging.getLogger(__name__)

MODES: tuple[str, ...] = ("fts", "vector", "hybrid")
BRANCHES: tuple[str, ...] = ("vector", "fts")

# Standard RRF damping constant; keeps any single ranking from dominating.
RRF_K = 60

# Each branch fetches this many times the requested limit when the rankings are
# fused, so the fusion has something to work with.
HYBRID_OVERFETCH = 4

# Characters of the verbatim chunk shown when there is no headline to show.
SNIPPET_CHARS = 300

# Query embeddings kept in memory. One search is one embedding request and the
# quota is counted per request per minute; a demo re-runs the same query with
# different filters and modes many times over.
_EMBED_CACHE_SIZE = 256
_embed_cache: OrderedDict[tuple[str, int, str], list[float]] = OrderedDict()


class EmbeddingUnavailable(RuntimeError):
    """The query could not be embedded, so the vector branch cannot run.

    Raised after the retries are exhausted or when no key is configured. The
    full-text branch needs no API and is the fallback to offer.
    """


@dataclass
class SearchResult:
    """One ranking plus what it took to produce it."""

    query: str
    mode: str
    limit: int
    fetch: int
    hits: list[dict[str, Any]]
    debug: dict[str, Any] = field(default_factory=dict)


_HEADLINE_OPTIONS = "StartSel=<mark>, StopSel=</mark>, MaxFragments=3, MaxWords=35, MinWords=15"

_TSQUERY = """websearch_to_tsquery('public.czech', %s::text)
                || websearch_to_tsquery('public.czech_literal', %s::text)"""

# Inner rankings: only the id and the score, so the ordering stays cheap.
_VECTOR_CANDIDATES = """
    SELECT c.chunk_id, 1 - (c.embedding <=> %s::vector) AS score
    FROM public.document_chunks c
    JOIN public.documents d ON d.id = c.document_id
    WHERE c.embedding IS NOT NULL{filters}
    ORDER BY c.embedding <=> %s::vector
    LIMIT %s
"""

_FTS_CANDIDATES = """
    SELECT c.chunk_id, ts_rank(c.fts_chunk, q.query) AS score
    FROM public.document_chunks c
    JOIN public.documents d ON d.id = c.document_id,
         LATERAL (SELECT {tsquery}) AS q(query)
    WHERE c.fts_chunk @@ q.query{filters}
    ORDER BY score DESC, c.document_id, c.chunk_index
    LIMIT %s
"""

# Outer query: everything the caller sees, computed for the survivors only.
_HYDRATE = """
SELECT r.score,
       c.chunk_id, c.document_id, c.chunk_index, c.section, c.content_kind,
       c.page_from, c.page_to, c.chunk_raw,
       d.title, d.locality, d.report_date, d.author, d.report_type,
       d.extraction_json->>'municipality' AS municipality,
       d.extraction_json->>'author_organization' AS organization,
       c.fts_chunk @@ q.query AS lexical_match,
       CASE WHEN c.fts_chunk @@ q.query
            THEN ts_headline('public.czech', c.chunk_raw, q.query, '{headline}')
       END AS headline
FROM ({candidates}) AS r
JOIN public.document_chunks c ON c.chunk_id = r.chunk_id
JOIN public.documents d ON d.id = c.document_id,
     LATERAL (SELECT {tsquery}) AS q(query)
ORDER BY r.score DESC, c.document_id, c.chunk_index
"""

_TSQUERY_TEXT = """
SELECT websearch_to_tsquery('public.czech', %s::text)::text,
       websearch_to_tsquery('public.czech_literal', %s::text)::text
"""

_LIST_QUERY = """
SELECT d.id, d.title, d.author, d.report_date, d.report_type, d.locality,
       d.extraction_json->>'municipality' AS municipality,
       d.extraction_json->>'author_organization' AS organization,
       count(c.chunk_id) AS chunks,
       count(c.embedding) AS chunks_with_vector
FROM public.documents d
LEFT JOIN public.document_chunks c ON c.document_id = d.id
WHERE TRUE{filters}
GROUP BY d.id
ORDER BY d.report_date DESC NULLS LAST, d.title
"""

_DOCUMENT_QUERY = """
SELECT d.id, d.source_file, d.title, d.report_type, d.locality, d.report_date,
       d.author, d.client, d.summary, d.extraction_json, d.extraction_model,
       d.extraction_schema_version,
       (SELECT count(*) FROM public.document_chunks c WHERE c.document_id = d.id) AS chunks
FROM public.documents d
WHERE d.id = %s
"""

_CONTEXT_QUERY = """
SELECT c.chunk_index, c.section, c.content_kind, c.page_from, c.page_to, c.chunk_raw
FROM public.document_chunks c
WHERE c.document_id = %s AND c.chunk_index BETWEEN %s AND %s
ORDER BY c.chunk_index
"""

_COUNTS_QUERY = """
SELECT (SELECT count(*) FROM public.documents) AS documents,
       (SELECT count(*) FROM public.document_chunks) AS chunks,
       (SELECT count(*) FROM public.document_chunks WHERE embedding IS NOT NULL) AS chunks_with_vector
"""

# Facets are counted over the same column expressions the filters compare
# against, so a value picked from a facet is guaranteed to filter.
_FACET_FIELDS: tuple[str, ...] = ("author", "organization", "municipality", "client", "report_type")


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


def query_embedding(text: str, settings: Settings) -> tuple[list[float], bool]:
    """Return the query embedding and whether it came from the in-memory cache."""
    key = (settings.embedding_model, settings.embedding_dimensions, text)
    cached = _embed_cache.get(key)
    if cached is not None:
        _embed_cache.move_to_end(key)
        return cached, True
    vector = embed_query(text, settings.embedding_model, settings.embedding_dimensions)
    _embed_cache[key] = vector
    while len(_embed_cache) > _EMBED_CACHE_SIZE:
        _embed_cache.popitem(last=False)
    return vector, False


def to_pgvector(values: list[float]) -> str:
    """Format an embedding as a pgvector literal."""
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


def _rows_to_dicts(cursor) -> list[dict[str, Any]]:
    """Convert a cursor result to a list of dicts."""
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def snippet(text: str | None, chars: int = SNIPPET_CHARS) -> str:
    """Return the start of a chunk with its whitespace collapsed."""
    return " ".join((text or "").split())[:chars]


def _hit(row: dict[str, Any]) -> dict[str, Any]:
    """Turn a database row into a hit with every score slot present."""
    hit = {key: value for key, value in row.items() if key != "score"}
    hit["snippet"] = snippet(row.get("chunk_raw"))
    for name in BRANCHES:
        hit[f"{name}_rank"] = None
        hit[f"{name}_score"] = None
    hit["rrf_score"] = None
    return hit


def rank_hits(rows: list[dict[str, Any]], branch: str, limit: int) -> list[dict[str, Any]]:
    """Return the top ``limit`` rows of one branch as hits carrying that branch's rank."""
    hits: list[dict[str, Any]] = []
    for rank, row in enumerate(rows[:limit], start=1):
        hit = _hit(row)
        hit[f"{branch}_rank"] = rank
        hit[f"{branch}_score"] = float(row["score"])
        hits.append(hit)
    return hits


def reciprocal_rank_fusion(
    rankings: dict[str, list[dict[str, Any]]], limit: int
) -> list[dict[str, Any]]:
    """Merge several rankings by Reciprocal Rank Fusion.

    ``rankings`` maps a branch name to its rows, best first. Every fused hit
    keeps the rank and score it had in each branch it appeared in, and ``None``
    for the branches it did not.
    """
    fused: dict[str, dict[str, Any]] = {}
    for branch, ranking in rankings.items():
        for rank, row in enumerate(ranking, start=1):
            key = str(row["chunk_id"])
            hit = fused.get(key)
            if hit is None:
                hit = _hit(row)
                hit["rrf_score"] = 0.0
                fused[key] = hit
            hit[f"{branch}_rank"] = rank
            hit[f"{branch}_score"] = float(row["score"])
            hit["rrf_score"] += 1.0 / (RRF_K + rank)
    ordered = sorted(fused.values(), key=lambda hit: hit["rrf_score"], reverse=True)
    return ordered[:limit]


def annotate_across(hits: list[dict[str, Any]], rankings: dict[str, list[dict[str, Any]]]) -> None:
    """Fill in, for every hit, its rank and score in each branch that ran.

    A full-text hit that also sits at position 3 of the vector candidates
    should say so, whichever list it is being shown in.
    """
    positions: dict[str, dict[str, tuple[int, float]]] = {
        branch: {str(row["chunk_id"]): (rank, float(row["score"])) for rank, row in enumerate(rows, start=1)}
        for branch, rows in rankings.items()
    }
    for hit in hits:
        key = str(hit["chunk_id"])
        for branch, index in positions.items():
            found = index.get(key)
            if found is not None:
                hit[f"{branch}_rank"], hit[f"{branch}_score"] = found


def _hydrate(candidates_sql: str) -> str:
    return _HYDRATE.format(candidates=candidates_sql, tsquery=_TSQUERY, headline=_HEADLINE_OPTIONS)


def _fetch_branches(
    connection,
    query: str,
    filters: Filters,
    fetch: int,
    *,
    want_vector: bool,
    want_fts: bool,
    settings: Settings,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Run the requested branches and return their rows plus timing and diagnostics."""
    filter_sql, filter_params = filters.where(scope="chunks")
    debug: dict[str, Any] = {
        "filters": filters.describe(),
        "filter_sql": filter_sql.strip(),
        "filter_params": [str(param) for param in filter_params],
        "embedding_model": settings.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions,
        "rrf_k": RRF_K,
        "fetch": fetch,
    }
    rankings: dict[str, list[dict[str, Any]]] = {}
    cursor = connection.cursor()
    try:
        if want_vector:
            started = time.perf_counter()
            try:
                vector, cached = query_embedding(query, settings)
            except Exception as exc:  # noqa: BLE001 - every cause has the same remedy
                raise EmbeddingUnavailable(f"{type(exc).__name__}: {exc}") from exc
            debug["embed_ms"] = round((time.perf_counter() - started) * 1000, 1)
            debug["embedding_cached"] = cached
            literal = to_pgvector(vector)
            started = time.perf_counter()
            cursor.execute(
                _hydrate(_VECTOR_CANDIDATES.format(filters=filter_sql)),
                [literal, *filter_params, literal, fetch, query, query],
            )
            rankings["vector"] = _rows_to_dicts(cursor)
            debug["vector_ms"] = round((time.perf_counter() - started) * 1000, 1)
            debug["vector_candidates"] = len(rankings["vector"])

        if want_fts:
            started = time.perf_counter()
            cursor.execute(
                _hydrate(_FTS_CANDIDATES.format(filters=filter_sql, tsquery=_TSQUERY)),
                [query, query, *filter_params, fetch, query, query],
            )
            rankings["fts"] = _rows_to_dicts(cursor)
            debug["fts_ms"] = round((time.perf_counter() - started) * 1000, 1)
            debug["fts_candidates"] = len(rankings["fts"])

        cursor.execute(_TSQUERY_TEXT, [query, query])
        czech, literal_query = cursor.fetchone()
        debug["tsquery"] = {"czech": czech, "czech_literal": literal_query}
    finally:
        cursor.close()
    return rankings, debug


def run_search(
    connection,
    query: str,
    mode: str,
    filters: Filters | None = None,
    limit: int = 5,
    settings: Settings | None = None,
) -> SearchResult:
    """Search in one mode.

    Raises:
        ValueError: On an unknown mode or an empty query.
        EmbeddingUnavailable: When a mode needing the vector branch cannot embed.
    """
    if mode not in MODES:
        raise ValueError(f"Unknown mode {mode!r}; expected one of {MODES}")
    query = " ".join(query.split())
    if not query:
        raise ValueError("Nothing to search for")
    filters = filters or Filters()
    settings = settings or load_settings()
    fetch = limit * HYBRID_OVERFETCH if mode == "hybrid" else limit

    rankings, debug = _fetch_branches(
        connection,
        query,
        filters,
        fetch,
        want_vector=mode in ("vector", "hybrid"),
        want_fts=mode in ("fts", "hybrid"),
        settings=settings,
    )
    if mode == "hybrid":
        hits = reciprocal_rank_fusion(rankings, limit)
    else:
        hits = rank_hits(rankings[mode], mode, limit)
    annotate_across(hits, rankings)
    return SearchResult(query=query, mode=mode, limit=limit, fetch=fetch, hits=hits, debug=debug)


def compare(
    connection,
    query: str,
    filters: Filters | None = None,
    limit: int = 5,
    settings: Settings | None = None,
) -> dict[str, SearchResult]:
    """Run every mode on one query and return them keyed by mode.

    One embedding request and two SQL queries serve all three rankings; the
    single-branch views are the head of their over-fetched candidate list, which
    is the same head a direct search would return.
    """
    query = " ".join(query.split())
    if not query:
        raise ValueError("Nothing to search for")
    filters = filters or Filters()
    settings = settings or load_settings()
    fetch = limit * HYBRID_OVERFETCH

    rankings, debug = _fetch_branches(
        connection, query, filters, fetch, want_vector=True, want_fts=True, settings=settings
    )
    results: dict[str, SearchResult] = {}
    for mode in MODES:
        if mode == "hybrid":
            hits = reciprocal_rank_fusion(rankings, limit)
        else:
            hits = rank_hits(rankings[mode], mode, limit)
        annotate_across(hits, rankings)
        results[mode] = SearchResult(
            query=query, mode=mode, limit=limit, fetch=fetch, hits=hits, debug=dict(debug)
        )
    return results


def list_documents(connection, filters: Filters | None = None) -> list[dict[str, Any]]:
    """Return the documents matching the filter, newest first, with chunk counts."""
    filter_sql, filter_params = (filters or Filters()).where(scope="documents")
    cursor = connection.cursor()
    try:
        cursor.execute(_LIST_QUERY.format(filters=filter_sql), filter_params)
        return _rows_to_dicts(cursor)
    finally:
        cursor.close()


def get_document(connection, document_id: str) -> dict[str, Any] | None:
    """Return one document with its full extraction, or None."""
    cursor = connection.cursor()
    try:
        cursor.execute(_DOCUMENT_QUERY, [document_id])
        rows = _rows_to_dicts(cursor)
    finally:
        cursor.close()
    return rows[0] if rows else None


def neighbours(
    connection, document_id: str, chunk_index: int, before: int = 1, after: int = 1
) -> list[dict[str, Any]]:
    """Return the chunks around one chunk, in document order, the chunk included.

    ``chunk_index`` is contiguous from 0 within a document and unique per
    document, so a range over it is the reading order of the report.
    """
    cursor = connection.cursor()
    try:
        cursor.execute(
            _CONTEXT_QUERY,
            [document_id, max(0, chunk_index - before), chunk_index + after],
        )
        rows = _rows_to_dicts(cursor)
    finally:
        cursor.close()
    for row in rows:
        row["is_hit"] = row["chunk_index"] == chunk_index
    return rows


def facets(connection) -> dict[str, Any]:
    """Return the values every filter can take, with document counts.

    Keyed by filter name so a client can map a facet straight onto the filter
    it feeds. ``documents`` is the full listing for a per-document restriction,
    ``years`` the span of report dates, ``content_kinds`` the chunk split.
    """
    out: dict[str, Any] = {}
    cursor = connection.cursor()
    try:
        for name in _FACET_FIELDS:
            expression = column_expression(name)
            cursor.execute(
                f"SELECT {expression} AS value, count(*) AS count"
                f" FROM public.documents d"
                f" WHERE {expression} IS NOT NULL AND {expression} <> ''"
                f" GROUP BY 1 ORDER BY count DESC, value"
            )
            out[name] = _rows_to_dicts(cursor)
        cursor.execute(
            "SELECT min(extract(year FROM report_date))::int,"
            " max(extract(year FROM report_date))::int FROM public.documents"
        )
        low, high = cursor.fetchone()
        out["years"] = {"min": low, "max": high}
        cursor.execute(
            "SELECT content_kind AS value, count(*) AS count, count(embedding) AS with_vector"
            " FROM public.document_chunks GROUP BY 1 ORDER BY 1"
        )
        out["content_kinds"] = _rows_to_dicts(cursor)
    finally:
        cursor.close()
    out["documents"] = list_documents(connection)
    return out


def corpus_counts(connection) -> dict[str, int]:
    """Return how many documents and chunks the database holds."""
    cursor = connection.cursor()
    try:
        cursor.execute(_COUNTS_QUERY)
        return _rows_to_dicts(cursor)[0]
    finally:
        cursor.close()
