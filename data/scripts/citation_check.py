"""Verify a generated answer against the sources it cites.

The model returns every sentence with the ids it cites and a verbatim quote
from each. That quote is the whole point: a pointer the server can follow.
Gemini has no citation API for sources of our own, the way Claude or Vertex
Grounded Generation do, so the guarantee is rebuilt here. Anthropic's advice
on hallucinations is the same in spirit - make the model quote, then check the
quote, and drop what has no support.

Four things are checked, in this order, and the first failure names the
sentence:

    invalid_source      a cited id is not among the sources
    unsupported         no id, or no quote
    quote_not_found     the quote is in no cited source
    number_unsupported  a number in the sentence is in no cited source

The numbers matter as much as the words. In a geological report the dangerous
mistake is not a clumsy sentence, it is a depth of 0,5 m turned into 5 m, and
that check is cheap and deterministic.

Three things the check has to allow, all learned from the first run over the
golden set, where every one of them produced a false alarm:

- **Digits grouped by spaces.** A table prints "25 24 41" and a thousand is
  written "2 215", so a space may stand between the digits of a number. The
  boundaries still keep 96 from matching inside 960.
- **Numbers from the document header.** A source reaches the model with its
  document title, municipality, survey type, date and organisation, so a
  parcel number in the title or the year of the report is evidence the model
  was given. Quotes still have to come from the chunk text itself. The page
  and the section are deliberately left out of this: they are small integers
  in the same range as the quantities the check exists to protect, so a page
  14 would quietly support "14 vrtů". The instructions tell the model to leave
  page and chapter numbers to the citation instead of the sentence.
- **Digits inside a name.** The borehole HV1 and the probe J16 carry digits
  that claim no value, so they are not read as numbers at all. Names are left
  to the quote check, and a name usually comes from the question anyway.

Comparison runs through ``text_match.py``, so doubled spaces and the kind of
dash do not matter. No API and no database, so an answer can be checked in a
test without credentials.
"""

from __future__ import annotations

import re
from typing import Any

from text_match import contains_normalized, normalize_for_match

VERIFIED = "verified"
INVALID_SOURCE = "invalid_source"
UNSUPPORTED = "unsupported"
QUOTE_NOT_FOUND = "quote_not_found"
NUMBER_UNSUPPORTED = "number_unsupported"

CHECKS = (VERIFIED, INVALID_SOURCE, UNSUPPORTED, QUOTE_NOT_FOUND, NUMBER_UNSUPPORTED)

_NOTES = {
    VERIFIED: "citát i čísla ověřeny ve zdroji",
    INVALID_SOURCE: "věta cituje zdroj, který v kontextu není",
    UNSUPPORTED: "věta nemá zdroj nebo doslovný citát",
    QUOTE_NOT_FOUND: "citát se v citovaném zdroji nenašel",
    NUMBER_UNSUPPORTED: "číslo z věty není v citovaných zdrojích",
}

# A number as a report writes it: 12, 0,5, 3.1, 5.10-6 becomes 5.10 and 6.
# A digit glued to a letter belongs to a name - the borehole HV1, the probe
# J16, the sample MJ17-520 - not to a quantity, so the lookbehind skips it.
# Names are therefore not checked here; the quote requirement covers them, and
# a name usually comes from the question rather than from a source.
_NUMBER = re.compile(r"(?<![^\W_])(?<![.,])\d+(?:[.,]\d+)*")

# Document fields that travel with every source in the prompt, so a number in
# them was given to the model as part of that source.
_HEADER_FIELDS = ("title", "municipality", "report_type", "organization", "report_date")


def numbers_in(text: str) -> list[str]:
    """Return the numbers a sentence claims, in order, without repeats."""
    return list(dict.fromkeys(_NUMBER.findall(normalize_for_match(text))))


def _has_number(haystack: str, number: str) -> bool:
    """Return whether ``haystack`` states this number, and not a longer one.

    A space may sit between the digits, because tables and thousands are
    printed that way.
    """
    pattern = r"(?<![\d.,])" + r"\s*".join(re.escape(char) for char in number) + r"(?![\d])"
    return re.search(pattern, haystack) is not None


def source_text(source: dict[str, Any]) -> str:
    """Return the chunk text a quote must come from."""
    return str(source.get("chunk_raw") or "")


def number_haystack(source: dict[str, Any]) -> str:
    """Return what a number may come from: the chunk text and the document header."""
    parts = [source_text(source)]
    parts += [str(source.get(field) or "") for field in _HEADER_FIELDS]
    return normalize_for_match(" ".join(parts))


def check_statement(statement: dict[str, Any], sources: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Check one sentence against the sources it cites; return it with a verdict."""
    ids = [int(value) for value in statement.get("source_ids") or []]
    quotes = [str(quote) for quote in statement.get("quotes") or [] if str(quote).strip()]
    text = str(statement.get("text") or "").strip()
    checked = {"text": text, "source_ids": ids, "quotes": quotes}

    unknown = [value for value in ids if value not in sources]
    if unknown:
        return {**checked, "check": INVALID_SOURCE, "note": f"{_NOTES[INVALID_SOURCE]}: {unknown}"}
    if not ids or not quotes:
        return {**checked, "check": UNSUPPORTED, "note": _NOTES[UNSUPPORTED]}

    cited = [sources[value] for value in ids]
    missing_quote = [
        quote for quote in quotes if not any(contains_normalized(source_text(source), quote) for source in cited)
    ]
    if missing_quote:
        return {**checked, "check": QUOTE_NOT_FOUND, "note": f"{_NOTES[QUOTE_NOT_FOUND]}: {missing_quote[0]!r}"}

    haystack = " ".join(number_haystack(source) for source in cited)
    missing_number = [number for number in numbers_in(text) if not _has_number(haystack, number)]
    if missing_number:
        return {
            **checked,
            "check": NUMBER_UNSUPPORTED,
            "note": f"{_NOTES[NUMBER_UNSUPPORTED]}: {', '.join(missing_number)}",
        }

    return {**checked, "check": VERIFIED, "note": _NOTES[VERIFIED]}


def check_answer(
    statements: list[dict[str, Any]], sources: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Check every sentence of an answer; return the sentences and a summary."""
    by_id = {int(source["id"]): source for source in sources}
    checked = [check_statement(statement, by_id) for statement in statements]
    counts: dict[str, int] = {check: 0 for check in CHECKS}
    for statement in checked:
        counts[statement["check"]] += 1
    cited = sorted({value for statement in checked for value in statement["source_ids"]})
    summary = {
        "statements": len(checked),
        "verified": counts[VERIFIED],
        "flagged": len(checked) - counts[VERIFIED],
        "checks": counts,
        "cited_sources": cited,
    }
    return checked, summary


def final_status(model_status: str, statements: list[dict[str, Any]]) -> str:
    """Return the status the user sees, after the checks had their say.

    A model that claims to have answered but leaves an unverified sentence is
    downgraded: the answer is then partial at best. An answer without a single
    verified sentence is not an answer.
    """
    if not statements:
        return "insufficient" if model_status == "answered" else model_status
    verified = sum(1 for statement in statements if statement["check"] == VERIFIED)
    if verified == 0:
        return "insufficient"
    if verified < len(statements):
        return "partial"
    return model_status
