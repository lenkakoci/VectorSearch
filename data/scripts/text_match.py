"""Loose text comparison between hand-written snippets and chunk text.

pdfminer text carries doubled spaces, non-breaking spaces, soft hyphens and
several kinds of dash, so a snippet retyped from a report - a golden-set
evidence string today, a quote in a generated answer later - rarely equals the
chunk byte for byte. Both sides go through the same normalisation before a
substring test:

- Unicode NFC, so a composed and a decomposed "ř" are the same letter;
- soft hyphens and zero-width spaces are removed, other spaces become " ";
- every dash becomes "-" and the spaces around it are dropped, so "0,4 – 1,0",
  "0,4–1,0" and "0,4 - 1,0" compare equal;
- runs of whitespace collapse to one space, and case is ignored.

Nothing else is loosened. Diacritics, digits, decimal commas and units must
match, because in a geological report those are the facts.
"""

from __future__ import annotations

import re
import unicodedata

_REMOVED = {ord(char): None for char in "\u00ad\u200b\ufeff"}
_DASHES = {ord(char): "-" for char in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"}
_SPACES = {ord(char): " " for char in "\u00a0\u2007\u2009\u200a\u202f"}
_TRANSLATION = {**_REMOVED, **_DASHES, **_SPACES}

_WHITESPACE = re.compile(r"\s+")
_SPACED_DASH = re.compile(r" ?- ?")


def normalize_for_match(text: str | None) -> str:
    """Return ``text`` in the canonical form every comparison here uses."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text).translate(_TRANSLATION)
    text = _WHITESPACE.sub(" ", text)
    text = _SPACED_DASH.sub("-", text)
    return text.strip().lower()


def contains_normalized(haystack: str | None, needle: str | None) -> bool:
    """Return whether ``needle`` occurs in ``haystack`` after normalisation.

    An empty needle never matches: evidence or a quote that normalises to
    nothing would otherwise match every chunk.
    """
    wanted = normalize_for_match(needle)
    return bool(wanted) and wanted in normalize_for_match(haystack)
