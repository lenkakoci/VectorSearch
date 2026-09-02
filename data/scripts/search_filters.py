"""Metadata filters for report search.

Both search branches are ordinary SQL - pgvector's ``<=>`` and ``@@`` over a
tsvector are operators, not a separate engine - so restricting a search by author
or municipality is a question of what the ``WHERE`` clause can express. This
module turns what the user typed into that clause.

Filters arrive two ways and mean the same thing:

    search_reports.py "autor:Poul obec:Lednice hladina vody"
    search_reports.py "hladina vody" --autor Poul --obec Lednice

The prefixes are parsed here, not by an LLM. A model asked to write SQL can
invent a column or return a query that is quietly wrong, and in a corpus of
geological reports a quietly wrong answer is a safety problem - the same reason
``EXTRACTION_INSTRUCTIONS`` forbids the model from inferring anything.

**SQL is only ever assembled from the fixed vocabulary in ``_FIELDS``.** Values
always travel as ``%s`` parameters, so ``autor:'; DROP TABLE documents; --`` is
compared as a string and cannot become syntax. Never build a clause from user
text here.

No database and no API, so it can be exercised straight from a REPL.
"""

from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Field:
    """One filterable column: where it lives and how it is compared."""

    name: str
    sql: str
    kind: str


# The whole vocabulary. Adding a filter means adding a row here and an attribute
# to Filters - nothing else composes SQL.
_FIELDS: tuple[_Field, ...] = (
    _Field("author", "d.author ILIKE %s", "text"),
    _Field("client", "d.client ILIKE %s", "text"),
    _Field("locality", "d.locality ILIKE %s", "text"),
    _Field("municipality", "d.extraction_json->>'municipality' ILIKE %s", "text"),
    _Field("report_type", "d.report_type ILIKE %s", "text"),
    _Field("organization", "d.extraction_json->>'author_organization' ILIKE %s", "text"),
    _Field("date_from", "d.report_date >= %s", "date"),
    _Field("date_to", "d.report_date <= %s", "date"),
    _Field("document_ids", "d.id = ANY(%s::uuid[])", "uuid_list"),
)

_BY_NAME = {field.name: field for field in _FIELDS}

# Czech and English spellings of the same filter. Reports are written in Czech
# and the scripts are in English, so both get to be first-class.
_PREFIXES: dict[str, str] = {
    "autor": "author",
    "author": "author",
    "klient": "client",
    "client": "client",
    "lokalita": "locality",
    "locality": "locality",
    "obec": "municipality",
    "municipality": "municipality",
    "typ": "report_type",
    "type": "report_type",
    "org": "organization",
    "od": "date_from",
    "from": "date_from",
    "do": "date_to",
    "to": "date_to",
    "doc": "document_ids",
    "document": "document_ids",
}

# A prefix has to start the token, so "poznámka: text" in ordinary prose is not
# mistaken for one. Values may be quoted to carry spaces.
_PREFIX_RE = re.compile(r'(?:^|(?<=\s))(?P<key>[A-Za-z_]+):(?P<value>"[^"]*"|\S+)')

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

_LABELS = {
    "author": "autor",
    "client": "klient",
    "locality": "lokalita",
    "municipality": "obec",
    "report_type": "typ",
    "organization": "organizace",
    "date_from": "od",
    "date_to": "do",
    "document_ids": "dokument",
}


@dataclass(frozen=True)
class Filters:
    """Metadata restrictions applied to every branch of a search."""

    author: str | None = None
    client: str | None = None
    locality: str | None = None
    municipality: str | None = None
    report_type: str | None = None
    organization: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    document_ids: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        """Return whether nothing is restricted."""
        return not any(getattr(self, field.name) for field in _FIELDS)

    def merge(self, other: Filters) -> Filters:
        """Combine with ``other``, keeping this object's values on a clash.

        Used to fold command-line flags into what was parsed out of the query
        string; a prefix the user typed inline wins over a flag.
        """
        merged: dict[str, Any] = {}
        for field in _FIELDS:
            mine, theirs = getattr(self, field.name), getattr(other, field.name)
            if field.kind == "uuid_list":
                merged[field.name] = tuple(dict.fromkeys((*mine, *theirs)))
            else:
                merged[field.name] = mine if mine is not None else theirs
        return replace(self, **merged)

    def where(self) -> tuple[str, list[Any]]:
        """Return the SQL fragment and its parameters.

        The fragment starts with ``AND`` so it can be appended to a ``WHERE``
        that already has a condition, and is empty when nothing is filtered.
        """
        clauses: list[str] = []
        params: list[Any] = []
        for field in _FIELDS:
            value = getattr(self, field.name)
            if not value:
                continue
            clauses.append(field.sql)
            if field.kind == "text":
                params.append(f"%{value}%")
            elif field.kind == "uuid_list":
                params.append(list(value))
            else:
                params.append(value)
        if not clauses:
            return "", []
        return "\n  AND " + "\n  AND ".join(clauses), params

    def describe(self) -> str:
        """Return a one-line human summary for the search header."""
        parts: list[str] = []
        for field in _FIELDS:
            value = getattr(self, field.name)
            if not value:
                continue
            label = _LABELS[field.name]
            if field.kind == "text":
                parts.append(f"{label} ~ {value!r}")
            elif field.kind == "uuid_list":
                parts.append(f"{label}: {len(value)}x")
            else:
                parts.append(f"{label} {value}")
        return ", ".join(parts)


def parse_date_bound(value: str, *, end: bool) -> date | None:
    """Parse a date filter, widening a year or month to its edge.

    ``2019`` means the whole of 2019, so it becomes 1 January as a lower bound
    and 31 December as an upper one. Same idea for ``2019-09``.
    """
    text = value.strip()
    try:
        if re.fullmatch(r"\d{4}", text):
            year = int(text)
            return date(year, 12, 31) if end else date(year, 1, 1)
        if re.fullmatch(r"\d{4}-\d{2}", text):
            year, month = (int(part) for part in text.split("-"))
            day = calendar.monthrange(year, month)[1] if end else 1
            return date(year, month, day)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            year, month, day = (int(part) for part in text.split("-"))
            return date(year, month, day)
    except ValueError:
        pass
    logger.warning("Ignoring unparsable date %r; expected YYYY, YYYY-MM or YYYY-MM-DD", value)
    return None


def build_filters(**raw: Any) -> Filters:
    """Build Filters from raw strings, parsing dates and checking UUIDs."""
    values: dict[str, Any] = {}
    for name, value in raw.items():
        if value in (None, "", [], ()):
            continue
        if name not in _BY_NAME:
            raise KeyError(f"Unknown filter: {name}")
        kind = _BY_NAME[name].kind
        if kind == "date":
            parsed = parse_date_bound(str(value), end=(name == "date_to"))
            if parsed is not None:
                values[name] = parsed
        elif kind == "uuid_list":
            items = [value] if isinstance(value, str) else list(value)
            good = [item for item in items if _UUID_RE.match(str(item).strip())]
            for item in items:
                if item not in good:
                    logger.warning("Ignoring %r; not a document UUID", item)
            if good:
                values[name] = tuple(good)
        else:
            values[name] = str(value).strip()
    return Filters(**values)


def parse_query(text: str) -> tuple[str, Filters]:
    """Split ``field:value`` prefixes off a query string.

    Returns the remaining search text and the filters found in it. An
    unrecognised prefix is left in the text rather than dropped - ``hloubka:3``
    is far more likely to be something the user wants searched for than a filter
    that was meant to exist.
    """
    raw: dict[str, Any] = {}
    documents: list[str] = []
    spans: list[tuple[int, int]] = []

    for match in _PREFIX_RE.finditer(text):
        key = match.group("key").lower()
        name = _PREFIXES.get(key)
        if name is None:
            logger.warning("Unknown filter prefix %r; searching for it as text", f"{key}:")
            continue

        value = match.group("value").strip('"').strip()
        if not value:
            logger.warning("Empty value for %r; ignoring", f"{key}:")
            spans.append(match.span())
            continue

        if name == "document_ids":
            documents.append(value)
        elif name in raw:
            logger.warning("Filter %r given twice; keeping the first", f"{key}:")
        else:
            raw[name] = value
        spans.append(match.span())

    remaining = text
    for start, end in reversed(spans):
        remaining = remaining[:start] + remaining[end:]

    if documents:
        raw["document_ids"] = documents
    return " ".join(remaining.split()), build_filters(**raw)
