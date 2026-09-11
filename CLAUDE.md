# VectorSearch — Agent Guide

Internal pipeline that turns digital geological reports (geologické posudky) into
structured data and searchable embeddings in PostgreSQL.

## Business context

Geological surveys arrive as PDF reports: engineering-geological, hydrogeological,
geotechnical and remediation surveys of specific sites. They are long, structured
Czech documents describing subsoil conditions, groundwater levels, identified
risks and recommendations for construction.

The goal is twofold:

1. **Structured extraction** — pull comparable metadata out of every report
   (locality, cadastral area, author, client, date, survey type, findings) so
   reports can be filtered and cross-referenced.
2. **Semantic search** — answer questions like "kde byla zastižena mělká hladina
   podzemní vody" across the whole archive, with a citation back to the exact
   section of the source report.

## Pipeline

```
data/PDFs/*.pdf
   │  extract_reports.py    pdfminer per page → classify pages → normalise
   │                        → LLM structured output
   ▼
data/processed/markdown/<stem>.md
                        <stem>.pages.json      per-page text, page attribution
                        <stem>.pagekind.json   prose / form / empty per page
                        <stem>.removed.json    what normalisation deleted, and why
data/processed/extracted/<stem>.json     → documents table
   │  chunk_and_embed.py    section-aware chunking → embeddings (prose only)
   ▼
data/processed/chunks/<stem>.parquet     → document_chunks table
   │  import_reports.py     upsert into PostgreSQL
   ▼
PostgreSQL (pgvector HNSW + tsvector GIN)
   │  search_reports.py     vector or hybrid (RRF) retrieval
   ▼
results with section-level citation
```

`ingest.py` runs all three stages incrementally and is the normal entry point.
`check_pipeline.py` verifies the result of every stage, makes no API calls and
exits 1 on failure; `--triage` groups what needs a decision, `--removed` prints
what the normaliser deleted from each document and under which rule.

Corpus today: 16 documents, 2040 chunks, of which 1015 are annex and carry no
vector. Three source PDFs are scans without a text layer and are skipped.

## Four things to understand before changing anything

**The extraction schema is provisional.** It was written before any real report
was available. `data/scripts/schemas.py` is deliberately loose: `report_type` is
a free string rather than a `Literal`, and `extra_fields` collects anything the
schema does not cover. Aggregating `extra_fields` across real reports is how the
final schema gets discovered — see `.claude/skills/data-ingestion/SKILL.md`.

**The pipeline is incremental, not batch.** `data/processed/manifest.json` records
what was done under which parameters. Changing `SCHEMA_VERSION`, the model, or the
chunk parameters invalidates exactly the affected stages and everything after
them. Never write a stage that reprocesses everything unconditionally.

**A version is a promise that equal versions mean equal output.**
`MARKDOWN_VERSION` (normaliser), `SCHEMA_VERSION` (extraction) and
`CHUNKER_VERSION` (chunker) are what the manifest compares. Change the *logic* of
any of those modules without bumping its version and the manifest keeps the old
output and calls it current — nothing reports it. This happened: `content_kind`
changed from section-based to page-based without a bump and two documents kept
chunks from the old rule. Bump on every behavioural change, however small.

**Reports have annexes, and the pipeline knows it.** Borehole logs, laboratory
certificates and coordinate tables follow the last chapter with no headings of
their own. Without handling they inherited the last chapter's label - 130 of 216
chunks of one report were cited as "8.4. Závěrečné zhodnocení". Two separate
questions, two separate sources:

| question | decided by | where |
| --- | --- | --- |
| how is this chunk cited? | **position** — everything past the annex boundary is filed under `## Přílohy` | `markdown_normalizer._annex_start` |
| is it worth an embedding? | **page kind** — only a filled-in form is left without a vector | `chunk_and_embed.content_kind` from `<stem>.pagekind.json` |

That split is why borehole logs are cited as annex *and* still searchable by
meaning. Do not collapse it back into one signal: whichever signal wins, the
other property is lost. The full rules and their failure modes are in
`README.md` under "Jak vzniká struktura".

## Skills

| Skill | Load when |
| --- | --- |
| `.claude/skills/add-reports/SKILL.md` | New PDFs need to go into the corpus, or a document must be re-processed or verified. |
| `.claude/skills/data-ingestion/SKILL.md` | Working on extraction, chunking, embedding, import, or evolving the extraction schema. |
| `.claude/skills/local-runtime/SKILL.md` | Running Docker Compose, configuring PostgreSQL, or running the pipeline locally. |

## Model provider

Google Gemini via the native `google-genai` SDK, wired up in
[data/scripts/gemini_auth.py](data/scripts/gemini_auth.py).

Gemini's OpenAI-compatibility layer is deliberately **not** used: it exposes only
chat completions (no Responses API) and does not document the `dimensions`
parameter for embeddings. The native SDK also provides `task_type`, which the
compatibility layer lacks and which materially affects retrieval quality.

- Extraction: `GEMINI_MODEL` (default `gemini-3.7-flash`), structured output by
  passing the Pydantic class as `response_schema`, `temperature=0.0`.
- Embeddings: `GEMINI_EMBEDDING_MODEL` (default `gemini-embedding-001`),
  `output_dimensionality=1536`, `task_type=RETRIEVAL_DOCUMENT` for chunks and
  `RETRIEVAL_QUERY` for search queries. Both sides of that pair must match.
- 1536 dimensions, not Gemini's default 3072: a pgvector HNSW index accepts at
  most 2000. Truncated vectors are L2-normalised in `gemini_auth.normalize()`.

## PDF text and Czech search

**One PDF engine, not two.** `extract_reports.py` reads each page with pdfminer
and that single pass produces both the Markdown and `<stem>.pages.json`.
`locate_pages()` matches chunk text against page text, so the two must come from
the same extractor — they used not to, and only 63% of chunks resolved a page
against 98% now. Do not reintroduce a second PDF library.

**Search is three layers of one SQL query.** Metadata (`ILIKE`, `>=` over
`documents`), full text (`fts_chunk @@ tsquery`) and meaning (`embedding <=>`)
compose in a single statement — pgvector and tsvector are operators, not separate
engines. `search_filters.py` turns `autor:Poul obec:Lednice hladina vody` into
the metadata half and leaves the rest as the query. **Never let a model write
SQL here**: it can invent a column or return a quietly wrong result, which in
this corpus is a safety problem, the same reason extraction may not infer. If
natural language is ever wanted, have the model fill a validated Pydantic filter
object and compose the SQL from that.

**Czech full-text needs a dictionary.** PostgreSQL ships no Czech stemmer, so
`simple` made whole queries unanswerable — a section titled "vrtů pro tepelné
čerpadlo" could not be found by searching "vrty pro tepelné čerpadlo". Chunks are
now indexed under two configurations at once (`czech` for morphology,
`czech_literal` for the previous accent-stripped literal behaviour) and
`search_reports.py` ORs `websearch_to_tsquery` over both. The dictionary comes
from `postgres/Dockerfile`; see `.claude/skills/data-ingestion/SKILL.md` for why
neither configuration works alone.

## Traps this project has already fallen into

- **An exit code of 0 is not verification.** A run can finish cleanly while part of
  its output no longer matches the code that made it. Verify by recomputing: load
  the Markdown, chunk it again, and compare with the parquet and the database.
- **Verify after each paid batch, not at the end.** Two regressions (page
  attribution falling to 7-33%, stale `content_kind`) surfaced only in the checks
  and each meant re-embedding. Run `check_pipeline.py` before the next batch.
- **Czech characters do not survive the shell.** A document list passed as
  arguments arrives as `Orli?ky`. Call `ingest.main([...])` from Python with names
  read from the manifest.
- **A cover page measures as a form** - short lines, no verbs. The classifier
  reclaims a leading run of up to three form pages as the cover; a longer cover
  would slip past that.
- **A sentence opening with a number looks like a heading.** Anything locating
  headings must check the number against the contents-page outline.
- **Two concurrent `--force` runs write the same files.** Run long regenerations
  in the background once, and wait for them.

## Proposed next work

In order of readiness. None has been started.

**1. Aggregate `extra_fields` and settle the extraction schema.** Most ready.
Extraction repeatedly reports the same keys across documents - `cislo_zakazky`,
`cislo_geofond`, `hydrogeologicky_rajon`, `souradnice_vrtu_sjtsk`,
`hloubka_vrtu`, `vystroj_vrtu` - so for the first time there is enough data to
promote fields and tighten `report_type` to a `Literal`. The procedure is in
`.claude/skills/data-ingestion/SKILL.md` ("Evolving the extraction schema"):
aggregate `extra_fields` and `missing_fields` in SQL, edit `schemas.py`, bump
`SCHEMA_VERSION`, add an `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migration.
Re-extraction reads cached Markdown, so no PDF is re-parsed - but every document
is extracted again, which is paid.

**2. Measure search quality.** Nothing measures relevance today:
`check_pipeline.py` verifies artefacts, and "is this chunking better" has been
answered by inspecting section labels. Build a small golden set - realistic
queries in Czech, each with the document and section that should answer it,
including morphology cases ("vrty" vs "vrtů") and annex-only facts (a borehole
number) - and report recall@k / MRR per search mode. Worth doing *before* the
next retrieval change (reranker, parent-child expansion), or its effect will be
guessed again. The query embedding is the only cost.

**3. Split bundles into their sub-reports.** Largest open structural issue.
`GF_P188240_ZZ Sedmirohé 10 sond` is eleven reports under one cover (sub-report
cover pages at 1, 22, 43, 89, 108, 131, 150, 173, 197, 220, 242) and `Metan jih`
is five. `_extract_toc` takes the first title for each section number across all
contents blocks, so eleven outlines collapse into one of nine entries, and a
sub-report's `3.2. Podzemní vody` lands after `8. Závěr` - 59 chunks of Sedmirohé
and 21 of Metan jih sit under it. `check_pipeline.py --removed` shows the bundle
at a glance: eleven separate contents blocks. The fix touches document identity
(one source file, several `documents` rows), extraction (one call per
sub-report) and citations, so it wants its own design first.

Also open, smaller: ZZ_Pazderna keeps 34 chunks under `6.1 SEZNAM NOREM` because
its annex has no form pages after the last heading, so there is no boundary to
find; Monitoring has one chunk without a section (its front matter, since no
title is promoted); three scans await OCR.

## Always-on engineering rules

- Python is `uv`-managed. Run scripts from `data/scripts` with `uv run python <script>.py`.
- Converting and checking cost nothing; extraction and embeddings cost money.
  Never run the paid stages on a document whose Markdown nobody has looked at —
  the procedure is in `.claude/skills/add-reports/SKILL.md`.
- Use Pydantic models for structured data and FastAPI if an API is ever added.
- Public functions and classes need useful docstrings. Use `logging`, never `print`,
  outside of CLI output intended for the user.
- Keep comments rare and only for non-obvious logic.
- Use disposable `adhoc_*.py` scripts for investigation and delete them afterwards.
- **Never commit secrets.** Credentials live in `.env` files; only `.env.template`
  is tracked.
- **Never commit source reports.** `data/PDFs/` is gitignored — the documents are
  internal to the organisation.
- `data/processed/` is a reproducible cache. Regenerate it, do not hand-edit it.
- SQL in `data/scripts/sql/` must be re-runnable: `CREATE TABLE IF NOT EXISTS`,
  never `DROP TABLE`. The database accumulates real documents.
- Extraction must be grounded strictly in the document text. No inferred facts,
  no filling gaps from general knowledge.
