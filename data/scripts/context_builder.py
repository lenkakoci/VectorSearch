"""Turn graded search hits into the sources a model may answer from.

Retrieval returns forty candidates; an answer needs a handful. This module
picks them, decides what travels with each chunk, and renders the block the
model reads. No API and no database: the neighbour lookup arrives as a
callable, so everything here is testable without credentials.

What goes in, and why:

- the verbatim ``chunk_raw``, never ``chunk_text``, whose ``KONTEXT:`` prefix
  repeats a model-written summary on every chunk of a document;
- the document title, its municipality, survey type, date and organisation,
  once per document, because a report describes one site and a finding from
  another site must not be read as an answer;
- the section path, the pages and whether the chunk is body or annex, so the
  answer can be cited and the model knows when it reads a form;
- nothing else. The extraction summary is model-written and would be cited as
  if it were the report, and the client name is personal data the answer does
  not need.

Selection follows the grades. Only chunks that reach the relevance gate are
eligible, at most ``PER_DOCUMENT`` of them from one report in the first pass,
so a single long report cannot fill the context of a question that spans
several sites. Remaining slots are filled without that cap. The budget is
counted in the tokens already stored per chunk, so it costs no model call.

Neighbours are added only where they help: a chunk whose neighbour belongs to
the same section is a window of a section that was split, and reading it alone
can cut a sentence in half. Such a neighbour is added with the role
``kontext`` and stays citable.

Order inside the block is document by document, best-graded document first,
and chunk by chunk in reading order. The question comes last, which is what
Gemini's long-context guidance recommends.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

from rerank_service import MIN_GRADE

MAX_SOURCES = 8
TOKEN_BUDGET = 10000
PER_DOCUMENT = 3
MAX_NEIGHBOURS = 4

FOUND_ROLE = "nalezeno"
NEIGHBOUR_ROLE = "kontext"

# Rough fallback when a chunk carries no token count: Czech text runs about
# three characters to a token.
_CHARS_PER_TOKEN = 3


@dataclass
class ContextPack:
    """The sources handed to the model, and the block they were rendered into."""

    sources: list[dict[str, Any]]
    prompt: str
    tokens: int
    stats: dict[str, Any] = field(default_factory=dict)


def _tokens_of(hit: dict[str, Any]) -> int:
    """Return the token count of a chunk, estimated when the database has none."""
    stored = hit.get("token_count")
    if stored:
        return int(stored)
    return max(1, len(hit.get("chunk_raw") or "") // _CHARS_PER_TOKEN)


def reaches_gate(hit: dict[str, Any], min_grade: int = MIN_GRADE) -> bool:
    """Return whether a graded hit is relevant enough to answer from.

    Without a reranker there is no grade, and everything qualifies.
    """
    grade = hit.get("rerank_grade")
    return grade is None or grade >= min_grade


def select_evidence(
    hits: list[dict[str, Any]],
    *,
    min_grade: int = MIN_GRADE,
    max_sources: int = MAX_SOURCES,
    token_budget: int = TOKEN_BUDGET,
    per_document: int = PER_DOCUMENT,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Choose the chunks worth answering from, best graded first.

    Returns the chosen hits and statistics about what was dropped and why.
    """
    eligible = [hit for hit in hits if reaches_gate(hit, min_grade)]
    chosen: list[dict[str, Any]] = []
    taken: set[str] = set()
    per_doc: Counter[str] = Counter()
    tokens = 0
    over_budget = 0
    over_document = 0

    for capped in (True, False):
        for hit in eligible:
            key = str(hit["chunk_id"])
            if key in taken or len(chosen) >= max_sources:
                continue
            if capped and per_doc[str(hit["document_id"])] >= per_document:
                over_document += 1
                continue
            cost = _tokens_of(hit)
            if tokens + cost > token_budget:
                over_budget += 1
                continue
            chosen.append(hit)
            taken.add(key)
            per_doc[str(hit["document_id"])] += 1
            tokens += cost

    stats = {
        "candidates": len(hits),
        "eligible": len(eligible),
        "chosen": len(chosen),
        "documents": len(per_doc),
        "tokens": tokens,
        "dropped_below_gate": len(hits) - len(eligible),
        "dropped_over_budget": over_budget,
        "dropped_per_document": over_document,
    }
    return chosen, stats


def add_neighbours(
    chosen: list[dict[str, Any]],
    fetch_neighbours: Callable[[str, int], list[dict[str, Any]]],
    *,
    tokens: int,
    token_budget: int = TOKEN_BUDGET,
    max_neighbours: int = MAX_NEIGHBOURS,
) -> tuple[list[dict[str, Any]], int, int]:
    """Add the neighbouring chunk of any chosen chunk whose section was split.

    ``fetch_neighbours`` takes a document id and a chunk index and returns the
    chunks around it. Only a neighbour from the same section is added, because
    only then does the selected chunk continue into it.
    """
    present = {str(hit["chunk_id"]) for hit in chosen}
    added: list[dict[str, Any]] = []

    for hit in chosen:
        if len(added) >= max_neighbours:
            break
        for neighbour in fetch_neighbours(str(hit["document_id"]), int(hit["chunk_index"])):
            if len(added) >= max_neighbours:
                break
            if neighbour.get("is_hit") or str(neighbour.get("chunk_id")) in present:
                continue
            if (neighbour.get("section") or "") != (hit.get("section") or ""):
                continue
            cost = _tokens_of(neighbour)
            if tokens + cost > token_budget:
                continue
            merged = {**hit, **neighbour, "role": NEIGHBOUR_ROLE}
            merged["rerank_grade"] = None
            merged["rerank_reason"] = None
            added.append(merged)
            present.add(str(neighbour.get("chunk_id")))
            tokens += cost

    return chosen + added, tokens, len(added)


def order_sources(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Number the sources: document by document, best graded first, in reading order."""
    order = {id(hit): position for position, hit in enumerate(hits)}
    by_document: dict[str, list[dict[str, Any]]] = {}
    for hit in hits:
        by_document.setdefault(str(hit["document_id"]), []).append(hit)

    def document_key(item: tuple[str, list[dict[str, Any]]]) -> tuple[int, int]:
        chunks = item[1]
        best = max((chunk.get("rerank_grade") or 0) for chunk in chunks)
        first = min(order[id(chunk)] for chunk in chunks)
        return (-best, first)

    sources: list[dict[str, Any]] = []
    number = 1
    for _, chunks in sorted(by_document.items(), key=document_key):
        for chunk in sorted(chunks, key=lambda chunk: int(chunk["chunk_index"])):
            source = dict(chunk)
            source["id"] = number
            source.setdefault("role", FOUND_ROLE)
            sources.append(source)
            number += 1
    return sources


def _pages(source: dict[str, Any]) -> str:
    """Return the page range of a chunk, empty when it has none."""
    start, end = source.get("page_from"), source.get("page_to")
    if not start:
        return ""
    return f"{start}" if not end or end == start else f"{start}-{end}"


def _json_line(payload: dict[str, Any]) -> str:
    """Serialise one line so chunk text cannot close the block it sits in."""
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")


def render_prompt(question: str, sources: list[dict[str, Any]]) -> str:
    """Render the sources block, with the question after it."""
    lines = ["<zdroje>"]
    current: str | None = None
    for source in sources:
        document = str(source["document_id"])
        if document != current:
            current = document
            lines.append(
                _json_line(
                    {
                        "dokument": source.get("title") or "",
                        "obec": source.get("municipality") or "",
                        "typ": source.get("report_type") or "",
                        "datum": str(source.get("report_date") or ""),
                        "zpracovatel": source.get("organization") or "",
                    }
                )
            )
        lines.append(
            _json_line(
                {
                    "id": source["id"],
                    "sekce": source.get("section") or "",
                    "strany": _pages(source),
                    "cast": "příloha" if source.get("content_kind") == "annex" else "tělo zprávy",
                    "role": source.get("role") or FOUND_ROLE,
                    "text": source.get("chunk_raw") or "",
                }
            )
        )
    lines += [
        "</zdroje>",
        "",
        f"<otazka>{' '.join(question.split())}</otazka>",
        "",
        "Odpověz podle pravidel v systémové instrukci.",
    ]
    return "\n".join(lines)


def build_context(
    question: str,
    hits: list[dict[str, Any]],
    fetch_neighbours: Callable[[str, int], list[dict[str, Any]]] | None = None,
    *,
    min_grade: int = MIN_GRADE,
    max_sources: int = MAX_SOURCES,
    token_budget: int = TOKEN_BUDGET,
    per_document: int = PER_DOCUMENT,
    max_neighbours: int = MAX_NEIGHBOURS,
) -> ContextPack:
    """Select the evidence, add neighbours, number the sources and render the block."""
    chosen, stats = select_evidence(
        hits,
        min_grade=min_grade,
        max_sources=max_sources,
        token_budget=token_budget,
        per_document=per_document,
    )
    tokens = stats["tokens"]
    neighbours = 0
    if fetch_neighbours is not None and chosen:
        chosen, tokens, neighbours = add_neighbours(
            chosen,
            fetch_neighbours,
            tokens=tokens,
            token_budget=token_budget,
            max_neighbours=max_neighbours,
        )
    sources = order_sources(chosen)
    prompt = render_prompt(question, sources)
    stats = {**stats, "neighbours": neighbours, "tokens": tokens, "sources": len(sources)}
    return ContextPack(sources=sources, prompt=prompt, tokens=tokens, stats=stats)
