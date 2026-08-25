"""Pydantic schema for structured extraction from geological reports.

PROVISIONAL SCHEMA
------------------
This schema was designed before any real report was available, so it is
deliberately loose:

- ``report_type`` is a free string, not a ``Literal``. Guessing the taxonomy of
  survey types before seeing a corpus would be premature.
- ``extra_fields`` is the schema-discovery mechanism. The model puts anything
  important that the schema does not cover in there. After the first batch of
  real reports, aggregate the recurring keys (radon index? excavation class?
  geotechnical category? referenced CSN standards?) and promote them to
  first-class fields.
- ``missing_fields`` forces the model to explicitly admit what it did not find.
  A cheap hallucination guard that works measurably better than ``| None`` alone.

Bumping ``SCHEMA_VERSION`` makes ``ingest.py`` re-extract every document from the
cached Markdown - no PDF re-parsing, no data loss.

Structured-output constraints (Gemini ``response_schema``):
- No ``dict[str, str]``: Gemini's schema dialect has no open-ended object with
  free-form keys. Hence ``list[ExtraField]``.
- No Pydantic defaults: every field is required. The model returns an empty list
  or ``null`` rather than omitting a key.

The model class is passed straight to ``types.GenerateContentConfig(
response_schema=...)`` and comes back validated as ``response.parsed``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Bump this whenever the schema below changes in a way that requires re-extraction.
SCHEMA_VERSION = 1


class ExtraField(BaseModel):
    """A fact worth keeping that the current schema has no field for."""

    key: str = Field(description="Short snake_case name of the fact, e.g. radonovy_index")
    value: str = Field(description="The value exactly as stated in the document")


class GeologicalReport(BaseModel):
    """Structured metadata extracted from a single geological report."""

    title: str = Field(description="Title of the report as printed on the document")
    report_type: str | None = Field(
        description="Type of survey as the document names it, e.g. inzenyrskogeologicky pruzkum. Null if not stated."
    )

    locality: str | None = Field(description="Free-text description of the site")
    municipality: str | None = Field(description="Municipality (obec)")
    cadastral_area: str | None = Field(description="Cadastral area (katastralni uzemi)")
    parcel_numbers: list[str] = Field(description="Parcel numbers, empty list if none stated")

    author: str | None = Field(description="Person who authored the report")
    author_organization: str | None = Field(description="Company that produced the report")
    client: str | None = Field(description="Client who commissioned the report (zadavatel)")
    report_date: str | None = Field(
        description="Date of the report as ISO YYYY-MM-DD. Null if absent or not resolvable to a full date."
    )

    summary: str = Field(
        description="3-5 sentence summary of the whole report, grounded strictly in its text"
    )
    key_findings: list[str] = Field(description="Key findings, conclusions and identified risks")
    recommendations: list[str] = Field(description="Recommendations stated in the report")

    missing_fields: list[str] = Field(
        description="Names of fields above that could not be found in the document"
    )
    extra_fields: list[ExtraField] = Field(
        description="Important facts present in the document that no field above covers"
    )


EXTRACTION_INSTRUCTIONS = """\
Jsi extrakcni nastroj pro ceske geologicke posudky. Z predloziteho textu vytahni \
strukturovana metadata.

ZAVAZNA PRAVIDLA:
- Vychazej VYHRADNE z predlozeneho textu dokumentu.
- Pokud udaj v dokumentu neni, vrat null (nebo prazdny seznam) a nazev pole uved \
  v missing_fields. Nikdy neodvozuj, nedopocitavej ani nedoplnuj z obecnych znalosti.
- Necituj domnenky. Kazda hodnota musi byt dohledatelna v textu.
- report_date vrat jako ISO YYYY-MM-DD. Pokud je v dokumentu jen mesic nebo rok, \
  vrat null a uved report_date v missing_fields.
- report_type opis tak, jak jej dokument nazyva; neprevadej na vlastni taxonomii.
- summary napis cesky, 3-5 vet, jako vecne shrnuti obsahu posudku.
- Do extra_fields uloz vse podstatne, co dokument obsahuje, ale zadne pole schematu \
  to nepokryva (napr. radonovy index, trida tezitelnosti, geotechnicka kategorie, \
  citovane normy, unosnost zakladove pudy). Klic pis snake_case bez diakritiky, \
  hodnotu opis z dokumentu.
"""
