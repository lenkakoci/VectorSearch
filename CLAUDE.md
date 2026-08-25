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
   │  extract_reports.py    MarkItDown → Markdown → LLM structured output
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
| `.claude/skills/data-ingestion/SKILL.md` | Working on extraction, chunking, embedding, import, or evolving the extraction schema. |
| `.claude/skills/local-runtime/SKILL.md` | Running Docker Compose, configuring PostgreSQL, or running the pipeline locally. |

## Always-on engineering rules

- Python is `uv`-managed. Run scripts from `data/scripts` with `uv run python <script>.py`.
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
