"""Find text in a report that speaks to a model instead of to a reader.

A geological report is data. Once its chunks reach an answering prompt, any
sentence in them that reads as an instruction - "ignoruj předchozí pokyny" - is
an attempt to steer the model, whether someone put it there on purpose or a
consultant pasted it from somewhere. The prompt already defends against this at
answering time: sources travel as JSON with ``<`` and ``>`` escaped and the
rules say the text of a source is data, never an instruction. That defence is
blind, though. It never tells anyone that a document in the corpus contains
such a sentence, and a corpus of internal reports is small enough that a human
should simply be told.

This module is the telling. It is pure text work: no API, no database, no
files, so ``check_pipeline.py`` can run it over the chunk parquet at no cost.

The hard part is precision, not recall. Czech reports are full of the word
"pokyn": every other one cites a *metodický pokyn MŽP* or works *podle pokynů
objednatele*. A rule that fires on those teaches the reader to ignore it, so
every rule here needs two things close together - an instruction being
overridden, a role being assigned, an output being dictated - and never a
keyword on its own.

Matching runs on the normalised text from ``text_match.py``: one line, single
spaces, lowercase, soft hyphens gone. That way a phrase broken across a PDF
line still matches, and the excerpt shown to the reader stays readable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from text_match import normalize_for_match

# How much text around a match goes into the excerpt.
_CONTEXT = 45


@dataclass(frozen=True)
class Rule:
    """One way a text can address a model."""

    name: str
    why: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class Finding:
    """One place where a rule matched."""

    rule: str
    why: str
    excerpt: str


def _rule(name: str, why: str, pattern: str) -> Rule:
    return Rule(name, why, re.compile(pattern))


# Gaps are bounded rather than open: "ignoruj" and "pokyny" mean something
# together in one sentence, and nothing at all a paragraph apart.
RULES: tuple[Rule, ...] = (
    _rule(
        "přepsání pokynů",
        "věta ruší dřívější zadání, což dokument nemá co dělat",
        r"\b(ignoruj\w*|nedbej\w*|zapomeň\w*|nevšímej\s+si|přestaň\s+se\s+řídit)\b.{0,40}?"
        r"\b(předchozí\w*|dosavadní\w*|výše\s+uveden\w+|všechn\w+)\b.{0,20}?"
        r"\b(pokyn\w*|instrukc\w*|zadání|příkaz\w*|pravidl\w*)",
    ),
    _rule(
        "přepsání pokynů",
        "anglická varianta téhož",
        r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}?"
        r"\b(instructions?|prompts?|rules?|directives?|guidelines?)\b",
    ),
    _rule(
        "nová role",
        "věta přiděluje modelu roli, kterou si má vzít místo své",
        r"\b(jsi|jste|budeš|chovej\s+se\s+jako|tvař\s+se\s+jako)\b.{0,30}?"
        r"\b(asistent\w*|jazykov\w+\s+model\w*|chatbot\w*|umělá\s+inteligence)\b",
    ),
    _rule(
        "nová role",
        "anglická varianta téhož",
        r"\b(you\s+are|act\s+as|pretend\s+to\s+be|behave\s+as|from\s+now\s+on\s+you)\b.{0,30}?"
        r"\b(ai|a\.i\.|assistant|language\s+model|chatbot)\b",
    ),
    _rule(
        "diktovaná odpověď",
        "věta předepisuje, co má model odpovědět",
        r"\b(odpověz\w*|napiš|vypiš|uveď|vrať|řekni)\b.{0,25}?"
        r"\b(pouze|jen|přesně|místo\s+toho|následující|toto|takto)\b",
    ),
    _rule(
        "diktovaná odpověď",
        "anglická varianta téhož",
        r"\b(respond|reply|answer|output|print|say)\b.{0,25}?"
        r"\b(only\s+with|exactly|instead|the\s+following|verbatim)\b",
    ),
    _rule(
        "systémový prompt",
        "text napodobuje rámec promptu, ne obsah zprávy",
        r"(system\s+prompt|systémov\w+\s+prompt|\[inst\]|<\|im_start\|>|###\s*instruction|"
        r"you\s+are\s+chatgpt)",
    ),
    _rule(
        "oslovení modelu",
        "text mluví přímo k modelu jménem",
        r"\b(chatgpt|gpt-[0-9]|claude|gemini|copilot|jazykov\w+\s+model\w*)\b.{0,30}?"
        r"\b(musíš|nesmíš|máš|prosím|odpověz\w*|ignoruj\w*|must|should|please|answer|ignore)\b",
    ),
)


def _excerpt(text: str, start: int, end: int) -> str:
    """Return the match with a little text around it, marked with brackets."""
    before = text[max(0, start - _CONTEXT) : start]
    after = text[end : end + _CONTEXT]
    lead = "…" if start - _CONTEXT > 0 else ""
    tail = "…" if end + _CONTEXT < len(text) else ""
    return f"{lead}{before}[{text[start:end]}]{after}{tail}"


def scan_text(text: str | None) -> list[Finding]:
    """Return every rule that matches ``text``, in the order the rules run.

    One rule reports one finding per text, because a sentence repeated in a
    chunk says nothing new; two different rules on the same sentence do.
    """
    normalized = normalize_for_match(text)
    if not normalized:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for rule in RULES:
        match = rule.pattern.search(normalized)
        if not match:
            continue
        key = (rule.name, match.group(0))
        if key in seen:
            continue
        seen.add(key)
        findings.append(Finding(rule.name, rule.why, _excerpt(normalized, match.start(), match.end())))
    return findings


def scan_chunks(chunks: Iterable[tuple[int, str]]) -> list[tuple[int, Finding]]:
    """Scan ``(chunk_index, text)`` pairs and return what matched, with the index."""
    found: list[tuple[int, Finding]] = []
    for index, text in chunks:
        found += [(index, finding) for finding in scan_text(text)]
    return found


def summarize(found: list[tuple[int, Finding]]) -> str:
    """Return a one-line summary for a report."""
    if not found:
        return "žádná věta nemluví k modelu"
    chunks = sorted({index for index, _ in found})
    rules = sorted({finding.rule for _, finding in found})
    where = ", ".join(f"#{index}" for index in chunks[:3]) + ("…" if len(chunks) > 3 else "")
    return f"{len(found)}x {', '.join(rules)} v chunku {where}"
