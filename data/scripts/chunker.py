"""Section-aware Markdown chunker for long geological reports.

The reference project never chunks anything - product descriptions are short and
get embedded whole. Reports are long documents, so this is written from scratch.

Strategy, in order:

1. Split on Markdown headings. A report has natural structure (Uvod /
   Geologicke pomery / Hydrogeologicke pomery / Zavery / Doporuceni) and user
   questions take the shape "what were the hydrogeological conditions", so the
   section is the semantically correct boundary. The heading path becomes
   ``section`` and is the primary citation unit.
2. Sections over ``max_tokens`` are split into token windows with overlap,
   preferring paragraph boundaries so a description of a geological profile is
   not torn mid-sentence.
3. Sections under ``min_tokens`` are merged into their neighbour. Otherwise you
   get worthless chunks like a bare heading or "Tab. 3".

800/100 rather than 500/100: report paragraphs are long and descriptive, and at
500 tokens a borehole profile description splits across chunks.

This module makes no API calls and touches no database, so chunk parameters can
be tuned without an OpenAI key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import tiktoken

# cl100k_base is close enough to the text-embedding-3-* tokenizer for sizing.
_ENCODING = tiktoken.get_encoding("cl100k_base")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


@dataclass
class Chunk:
    """One embeddable unit of a document."""

    chunk_index: int
    section: str | None
    text: str
    token_count: int


def count_tokens(text: str) -> int:
    """Return the number of tokens in ``text``."""
    return len(_ENCODING.encode(text))


@dataclass
class _Section:
    """A heading-delimited block of the document."""

    section: str | None
    body: str


def _split_sections(markdown: str) -> list[_Section]:
    """Split Markdown into sections, tracking the full heading path."""
    sections: list[_Section] = []
    heading_stack: list[str] = []
    current_path: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append(_Section(section=current_path, body=body))
        buffer.clear()

    for line in markdown.splitlines():
        match = _HEADING_RE.match(line)
        if not match:
            buffer.append(line)
            continue

        flush()
        level = len(match.group(1))
        title = match.group(2).strip()
        del heading_stack[level - 1 :]
        heading_stack.append(title)
        current_path = " > ".join(heading_stack)

    flush()

    # A document with no headings at all is a single unnamed section.
    if not sections and markdown.strip():
        sections.append(_Section(section=None, body=markdown.strip()))
    return sections


def _split_paragraphs(body: str) -> list[str]:
    """Split a section body into paragraphs, dropping empties."""
    return [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]


def _window_tokens(body: str, max_tokens: int, overlap: int) -> list[str]:
    """Split an oversized body into overlapping windows on paragraph boundaries.

    A single paragraph larger than ``max_tokens`` is split on the token grid,
    since there is no better boundary available.
    """
    windows: list[str] = []
    current: list[str] = []
    current_tokens = 0

    def flush_current() -> None:
        if current:
            windows.append("\n\n".join(current))

    for paragraph in _split_paragraphs(body):
        para_tokens = count_tokens(paragraph)

        if para_tokens > max_tokens:
            flush_current()
            current, current_tokens = [], 0
            windows.extend(_split_hard(paragraph, max_tokens, overlap))
            continue

        if current_tokens + para_tokens > max_tokens and current:
            flush_current()
            # Carry trailing paragraphs back as overlap.
            carry: list[str] = []
            carry_tokens = 0
            for previous in reversed(current):
                previous_tokens = count_tokens(previous)
                if carry_tokens + previous_tokens > overlap:
                    break
                carry.insert(0, previous)
                carry_tokens += previous_tokens
            current, current_tokens = carry, carry_tokens

        current.append(paragraph)
        current_tokens += para_tokens

    flush_current()
    return windows


def _split_hard(text: str, max_tokens: int, overlap: int) -> list[str]:
    """Split text on the token grid when no paragraph boundary is available."""
    tokens = _ENCODING.encode(text)
    step = max(1, max_tokens - overlap)
    pieces: list[str] = []
    for start in range(0, len(tokens), step):
        window = tokens[start : start + max_tokens]
        if not window:
            break
        pieces.append(_ENCODING.decode(window).strip())
        if start + max_tokens >= len(tokens):
            break
    return [piece for piece in pieces if piece]


def chunk_markdown(
    markdown: str,
    *,
    max_tokens: int = 800,
    overlap: int = 100,
    min_tokens: int = 150,
) -> list[Chunk]:
    """Split Markdown into embeddable chunks.

    Args:
        markdown: Document text, ideally with Markdown headings.
        max_tokens: Upper bound before a section is windowed.
        overlap: Token overlap carried between windows of the same section.
        min_tokens: Sections below this are merged into their neighbour.

    Returns:
        Chunks in document order, each with its heading path and token count.
    """
    if overlap >= max_tokens:
        raise ValueError("overlap must be smaller than max_tokens")

    pieces: list[tuple[str | None, str]] = []
    for section in _split_sections(markdown):
        heading_prefix = f"{section.section.split(' > ')[-1]}\n\n" if section.section else ""
        body = heading_prefix + section.body
        if count_tokens(body) > max_tokens:
            pieces.extend((section.section, window) for window in _window_tokens(body, max_tokens, overlap))
        else:
            pieces.append((section.section, body))

    merged = _merge_small(pieces, min_tokens, max_tokens)

    return [
        Chunk(chunk_index=index, section=section, text=text, token_count=count_tokens(text))
        for index, (section, text) in enumerate(merged)
    ]


def _merge_small(
    pieces: list[tuple[str | None, str]],
    min_tokens: int,
    max_tokens: int,
) -> list[tuple[str | None, str]]:
    """Merge undersized pieces forward, keeping the first piece's section label."""
    merged: list[tuple[str | None, str]] = []
    for section, text in pieces:
        if not merged:
            merged.append((section, text))
            continue

        previous_section, previous_text = merged[-1]
        previous_tokens = count_tokens(previous_text)
        current_tokens = count_tokens(text)

        undersized = previous_tokens < min_tokens or current_tokens < min_tokens
        if undersized and previous_tokens + current_tokens <= max_tokens:
            merged[-1] = (previous_section, f"{previous_text}\n\n{text}")
        else:
            merged.append((section, text))
    return merged
