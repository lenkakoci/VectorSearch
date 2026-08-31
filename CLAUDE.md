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
   │  extract_reports.py    pdfminer per page → normalise → LLM structured output
   ▼
data/processed/markdown/<stem>.md
data/processed/extracted/<stem>.json     → documents table
   │  chunk_and_embed.py    section-aware chunking → embeddings
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
exits 1 on failure.

## Two things to understand before changing anything

**The extraction schema is provisional.** It was written before any real report
was available. `data/scripts/schemas.py` is deliberately loose: `report_type` is
a free string rather than a `Literal`, and `extra_fields` collects anything the
schema does not cover. Aggregating `extra_fields` across real reports is how the
final schema gets discovered — see `.claude/skills/data-ingestion/SKILL.md`.

**The pipeline is incremental, not batch.** `data/processed/manifest.json` records
what was done under which parameters. Changing `SCHEMA_VERSION`, the model, or the
chunk parameters invalidates exactly the affected stages and everything after
them. Never write a stage that reprocesses everything unconditionally.

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

**Czech full-text needs a dictionary.** PostgreSQL ships no Czech stemmer, so
`simple` made whole queries unanswerable — a section titled "vrtů pro tepelné
čerpadlo" could not be found by searching "vrty pro tepelné čerpadlo". Chunks are
now indexed under two configurations at once (`czech` for morphology,
`czech_literal` for the previous accent-stripped literal behaviour) and
`search_reports.py` ORs `websearch_to_tsquery` over both. The dictionary comes
from `postgres/Dockerfile`; see `.claude/skills/data-ingestion/SKILL.md` for why
neither configuration works alone.

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
