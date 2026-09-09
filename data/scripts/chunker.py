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
be tuned without a Gemini API key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import tiktoken

# Local, offline, deterministic tokenizer used only to size chunks. It is NOT
# Gemini's tokenizer, so counts are approximate - expect Gemini to count roughly
# 10-30% more tokens on Czech text. That is fine here: the target is 800 tokens
# and gemini-embedding-001 accepts 2048, so the margin absorbs the drift. The
# alternative, client.models.count_tokens(), is a billable API round trip per
# chunk and would make chunk tuning slow and expensive.
_ENCODING = tiktoken.get_encoding("cl100k_base")

# Cache-invalidation key for the chunking *logic*, the counterpart of
# MARKDOWN_VERSION. The manifest already invalidates on the four tunable
# parameters, but a change to how this module splits, windows or merges leaves
# those untouched, so without this the database keeps chunks from the previous
# algorithm and the manifest reports them as current. Bump on any behavioural
# change here.
CHUNKER_VERSION = 3

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


@dataclass
class Chunk:
    """One embeddable unit of a document."""

    chunk_index: int
    section: str | None
    text: str
    token_count: int
    # ``text`` without the heading line prefixed to it. The heading is wording
    # the normaliser rebuilt from the contents page, so it appears nowhere in the
    # extracted page text; probing page attribution with it matches nothing.
    body: str = ""


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


def _tail_tokens(text: str, tokens: int) -> str:
    """Return the last ``tokens`` tokens of ``text``."""
    encoded = _ENCODING.encode(text)
    return _ENCODING.decode(encoded[-tokens:]).strip() if tokens > 0 else ""


def _window_tokens(body: str, max_tokens: int, overlap: int) -> list[str]:
    """Split an oversized body into overlapping windows on paragraph boundaries.

    A single paragraph larger than ``max_tokens`` is split on the token grid,
    since there is no better boundary available.
    """
    windows: list[str] = []
    current: list[str] = []
    current_tokens = 0

    def flush_current() -> None:
        if not current:
            return
        text = "\n\n".join(current)
        # The budget below counts paragraphs and separators, but joining can
        # retokenise across a boundary and add a little more. Measure the real
        # thing once per window and cut on the token grid if it still overshoots.
        if count_tokens(text) > max_tokens:
            windows.extend(_split_hard(text, max_tokens, overlap))
        else:
            windows.append(text)

    for paragraph in _split_paragraphs(body):
        para_tokens = count_tokens(paragraph)

        if para_tokens > max_tokens:
            flush_current()
            current, current_tokens = [], 0
            windows.extend(_split_hard(paragraph, max_tokens, overlap))
            continue

        # len(current) is how many "\n\n" separators the join will add.
        if current and current_tokens + para_tokens + len(current) > max_tokens:
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
            if not carry:
                # Every trailing paragraph is bigger than the overlap budget, so
                # whole-paragraph carry delivers nothing and consecutive windows
                # share no text at all. Cut the tail of the last one instead.
                tail = _tail_tokens(current[-1], overlap)
                if tail:
                    carry, carry_tokens = [tail], count_tokens(tail)
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
        # The heading goes on every window, not only the first. fts_chunk is
        # built from chunk_raw, so with it on the first alone a keyword search
        # for a section name cannot reach any continuation of a long section.
        heading_prefix = f"{section.section.split(' > ')[-1]}\n\n" if section.section else ""
        budget = max_tokens - count_tokens(heading_prefix)
        if count_tokens(heading_prefix + section.body) > max_tokens:
            pieces.extend(
                (section.section, heading_prefix + window)
                for window in _window_tokens(section.body, budget, overlap)
            )
        else:
            pieces.append((section.section, heading_prefix + section.body))

    merged = _merge_small(pieces, min_tokens, max_tokens)

    return [
        Chunk(
            chunk_index=index,
            section=section,
            text=text,
            token_count=count_tokens(text),
            body=_strip_heading(text, section),
        )
        for index, (section, text) in enumerate(merged)
    ]


def _strip_heading(text: str, section: str | None) -> str:
    """Return ``text`` without the heading line ``chunk_markdown`` prefixed."""
    if not section:
        return text
    prefix = f"{section.split(' > ')[-1]}\n\n"
    return text[len(prefix) :] if text.startswith(prefix) else text


def _merge_small(
    pieces: list[tuple[str | None, str]],
    min_tokens: int,
    max_tokens: int,
) -> list[tuple[str | None, str]]:
    """Merge undersized pieces into their neighbour within the same section.

    Merging across a heading boundary used to keep the *previous* piece's label,
    so an undersized section was cited as the one above it. Sections are the
    citation unit, so a small section now stays its own chunk rather than borrow
    somebody else's name for its text.
    """
    merged: list[tuple[str | None, str]] = []
    for section, text in pieces:
        if not merged:
            merged.append((section, text))
            continue

        previous_section, previous_text = merged[-1]
        if section != previous_section:
            merged.append((section, text))
            continue

        previous_tokens = count_tokens(previous_text)
        current_tokens = count_tokens(text)

        undersized = previous_tokens < min_tokens or current_tokens < min_tokens
        if undersized and previous_tokens + current_tokens <= max_tokens:
            merged[-1] = (previous_section, f"{previous_text}\n\n{text}")
        else:
            merged.append((section, text))
    return merged
