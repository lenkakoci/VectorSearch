---
name: data-ingestion
description: Use when working on report extraction, chunking, embedding, import, or evolving the extraction schema.
---

# Data Ingestion Skill

Load this skill when touching anything in `data/scripts/`.

## Stage map

| Stage | Script | Input | Output | Invalidated by |
| --- | --- | --- | --- | --- |
| markdown | `extract_reports.py` | `data/PDFs/*.pdf` | `processed/markdown/<stem>.md` | source sha256, `MARKDOWN_VERSION` |
| extract | `extract_reports.py` | cached Markdown | `processed/extracted/<stem>.json` | `SCHEMA_VERSION`, `GEMINI_MODEL` |
| chunk | `chunk_and_embed.py` | Markdown + extraction + page kinds | `processed/chunks/<stem>.parquet` | chunk params, `CHUNKER_VERSION`, embedding model/dims |
| import | `import_reports.py` | JSON + parquet | `documents`, `document_chunks` | any of the above |

`ingest.py` diffs `processed/manifest.json` against the current config and runs
only the stale stages, cascading forward. A stage whose output file is missing
counts as stale too, so deleting part of `processed/` to force a rebuild works.
Stages are also runnable standalone.

This skill is the machinery. For the procedure to follow when new reports arrive
see `add-reports`; for the Docker stack see `local-runtime`.

## Key files

- `schemas.py` — Pydantic extraction schema, `SCHEMA_VERSION`, and the grounding prompt.
- `manifest.py` — `stages_to_run()` holds the invalidation logic. Change carefully.
- `markdown_normalizer.py` — rebuilds structure in extracted page text, `MARKDOWN_VERSION`.
- `chunker.py` — pure function, no API or database. Testable without credentials.
- `check_pipeline.py` — verifies every stage's artefacts. No API calls, writes
  nothing, exits 1 on failure. Run it after touching anything here.
- `pipeline_common.py` — settings, paths, connection params. Add config here, not per-script.
- `gemini_auth.py` — client construction, retry predicate, embedding normalisation.
- `configure_postgresql.py` — generic runner over `sql/`. Connects through
  `pipeline_common`, so it carries no connection defaults of its own.

## Evolving the extraction schema

This is the main planned maintenance task. The schema in `schemas.py` is
provisional — it was written before real reports existed.

1. Drop new reports into `data/PDFs/`.
2. `uv run python extract_reports.py --markdown-only` — convert without spending
   LLM tokens, then read the Markdown to see how the reports are actually structured.
3. `uv run python ingest.py` on a handful of reports.
4. Aggregate what the model reported:
   ```sql
   SELECT jsonb_array_elements(extraction_json->'extra_fields')->>'key' AS field,
          count(*)
   FROM documents GROUP BY 1 ORDER BY 2 DESC;

   SELECT jsonb_array_elements_text(extraction_json->'missing_fields') AS field,
          count(*)
   FROM documents GROUP BY 1 ORDER BY 2 DESC;
   ```
   Frequent `extra_fields` keys are fields the schema is missing. Frequent
   `missing_fields` entries are fields that may not belong in the schema at all.
5. Edit `schemas.py`: add the promoted fields, drop the useless ones, and tighten
   `report_type` to a `Literal` once the taxonomy is clear. **Bump `SCHEMA_VERSION`.**
6. Add `sql/tables/03_alter_documents_typed_fields.sql` with
   `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` plus a backfill:
   `UPDATE documents SET radon_index = extraction_json->>'radon_index'`.
   Then map the new columns in `import_reports.py`.
7. `uv run python configure_postgresql.py && uv run python ingest.py`. The version
   bump re-extracts every document from cached Markdown — no PDF is re-parsed.

## Structured output constraints

Gemini's `response_schema` dialect has no open-ended object with free-form keys,
so `extra_fields` is `list[ExtraField]`, not `dict[str, str]`. Every field is
required — the model returns `null` or `[]` rather than omitting a key. Do not
add Pydantic defaults.

The Pydantic class is passed straight to `types.GenerateContentConfig(
response_schema=...)` and returns validated as `response.parsed`. Extraction runs
at `temperature=0.0` for reproducibility.

## Grounding

`EXTRACTION_INSTRUCTIONS` in `schemas.py` forbids inference. Keep it that way:
a hallucinated groundwater level in a geological report is a safety-relevant
error, not a cosmetic one. `missing_fields` forces the model to declare gaps
rather than fill them.

## Markdown normalisation

`pdf_pages()` reads the PDF one page at a time with pdfminer, and that single
pass feeds both the Markdown and `<stem>.pages.json`. Do not reintroduce a second
PDF library: `locate_pages()` matches chunk text against page text, so the two
must come from the same extractor. They used not to (MarkItDown for the text,
pypdf for the pages) and only 63% of chunks resolved a page; one engine gives
98%. pdfplumber, which MarkItDown used underneath, additionally invented pipe
tables out of multi-column layout and mangled accented glyphs on documents
pdfminer reads correctly.

Page text has no headings, so without `markdown_normalizer.py` a report becomes
one unbroken block, `chunker.py` falls back to a single unnamed section and every
chunk loses its section citation.

The normaliser runs inside `to_markdown()` and only on PDFs — `.md` inputs are
hand-written and pass through. Its steps are order-dependent; the module
docstring says why. Headings come from the report's own table of contents, which
is the only source precise enough to tell a heading from an annex list. Matching
is fuzzy because pdfminer drops glyphs it cannot map (one report's body reads
`2. P ehled p írodních pom r`), and where the contents page kept the intact
wording it wins, because the section label is what gets cited back to users.
Reports without a table of contents fall back to a numbering-continuity
heuristic. If neither recovers anything the run logs a warning rather than
inventing structure.

Tune it for free, no API key and no tokens:
```powershell
uv run python extract_reports.py --markdown-only
```
That regenerates the Markdown and, when the text actually changed, marks
extraction and chunks stale so the next `ingest.py` rebuilds them. Check the
result with `Select-String -Path ..\processed\markdown\<stem>.md -Pattern "^#"`.

## Chunking

Section-aware, from `chunker.py`: split on Markdown headings, window sections
over `CHUNK_MAX_TOKENS` with `CHUNK_OVERLAP_TOKENS`, merge sections under
`CHUNK_MIN_TOKENS`. The heading path becomes `section` and is the citation unit.

Rules that are easy to break, each covered by a test in
`data/scripts/tests/test_chunker.py`:

- **The limit is enforced after joining.** Separators between paragraphs count,
  and each window is measured once against the real joined text.
- **Overlap is always delivered.** When no whole trailing paragraph fits the
  overlap budget, the tail of the last one is cut instead.
- **The heading goes on every window**, since `fts_chunk` is built from
  `chunk_raw`. `Chunk.body` holds the text without it, and `locate_pages` must
  probe with `body` - the heading is wording rebuilt from the contents page and
  appears nowhere on the page it names. Probing with the heading dropped page
  coverage to 7-33%.
- **Merging stays within one section.** A small section is never glued to its
  neighbour under the neighbour's label.

**Bump `CHUNKER_VERSION` on any behavioural change**, including to
`content_kind`. The four tunable parameters alone cannot see a logic change.

## Annexes and `content_kind`

`page_classifier.py` marks each page `prose`, `form` or `empty` when the Markdown
is built, into `<stem>.pagekind.json`. A page is a form only when both its share
of long lines (< 12%) and its share of Czech function words (< 6%) are low - the
conjunction is what keeps borehole logs, which have ~1% function words but long
clause-shaped lines. The word list has no prepositions: forms use `od`, `do`,
`po` in their field labels as freely as prose does.

The normaliser sets form pages - and everything past the annex boundary - aside
before measuring anything, then appends them under `## Přílohy`. The boundary is
the first form page after the last page carrying a numbered heading *listed in
the contents page*.

`content_kind` is then taken from the page kind of each chunk's `page_from`, not
from its section: position decides the citation, page kind decides the
embedding. Annex chunks are imported with `embedding IS NULL`; the vector query
already filters on that, and `fts_chunk` still covers them. An unresolved page
counts as prose.

Thresholds are tuned to the fifteen reports converted so far (healthy 0.0-8.8%
form characters, broken 28.5-79.5%). Check a report from a new surveyor with
`check_pipeline.py --triage` before trusting them.

Tune without spending anything:
```powershell
uv run python chunk_and_embed.py --dry-run
```

`chunk_raw` is the verbatim text (cited to users, indexed for full-text search).
`chunk_text` is what was embedded and carries the Contextual Retrieval prefix
built from already-extracted metadata — no extra LLM call.

## Czech full-text search

PostgreSQL has no Czech Snowball stemmer, so this used to index with `simple`,
which does no morphology: a section titled "vrtů pro tepelné čerpadlo" could not
be found by searching "vrty pro tepelné čerpadlo".

`sql/tables/03_create_czech_fts.sql` creates two configurations and indexes
`chunk_raw` under **both**, because neither works alone:

| configuration | does |
| --- | --- |
| `czech` | hunspell morphology and stop words; lexemes keep diacritics |
| `czech_literal` | the previous behaviour: strip accents, index verbatim |

Morphology only matches when the query carries the same diacritics as the
document. Accent-stripping the hunspell dictionary to fix that was tried and
rejected — it collapses ~12000 of its 261000 entries and alters 517 affix rules,
and breaks lemmas that work intact. `search_reports.py` therefore ORs
`websearch_to_tsquery` over both configurations.

The dictionary files come from `postgres/Dockerfile` (`hunspell-cs`, GPL-2 data,
already UTF-8, only renamed). Without them `03` fails and the `simple` trigger
from `02` stays — the old behaviour, deliberately, so a stock image degrades
instead of breaking.

## Rules

- Never `TRUNCATE` or `DROP TABLE`. Reports are real data that accumulates.
- Parquet is per document, never one global file.
- Treat `data/processed/` as a regenerable cache; never hand-edit it.
- Never commit `data/PDFs/` contents.
