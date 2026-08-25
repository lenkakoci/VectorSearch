# Data Scripts

`uv`-managed pipeline for extracting, chunking, embedding and importing geological
reports. Run everything from this directory.

## Setup

```powershell
uv sync
Copy-Item .env.template .env
```

Fill in `GEMINI_API_KEY` (get one at <https://aistudio.google.com/apikey>) and
`PGPASSWORD`. Never commit `.env`.

## Normal use

```powershell
uv run python configure_postgresql.py   # once, and after any SQL change
uv run python ingest.py                 # whenever a new report arrives
uv run python search_reports.py "dotaz" --hybrid
```

## Scripts

| Script | Role |
| --- | --- |
| `gemini_auth.py` | Gemini client construction, retry predicate, and L2 normalisation of embeddings. |
| `configure_postgresql.py` | Generic SQL runner over `sql/extensions/` and `sql/tables/`. Taken verbatim. |
| `schemas.py` | Pydantic extraction schema, `SCHEMA_VERSION`, grounding prompt. |
| `manifest.py` | Pipeline state and stage-invalidation logic. |
| `pipeline_common.py` | Settings, paths, connection parameters, logging. |
| `chunker.py` | Section-aware Markdown chunker. No API, no database. |
| `extract_reports.py` | PDF → Markdown → LLM structured extraction. |
| `chunk_and_embed.py` | Chunking + embeddings → per-document parquet. |
| `import_reports.py` | JSON + parquet → PostgreSQL (upsert). |
| `ingest.py` | Incremental orchestrator. The usual entry point. |
| `search_reports.py` | Vector and hybrid (RRF) search from the CLI. |

## Flags worth knowing

```powershell
uv run python ingest.py --dry-run             # show the plan, change nothing
uv run python ingest.py --only report.pdf     # one file
uv run python ingest.py --force               # redo everything
uv run python ingest.py --skip-import         # stop before the database

uv run python extract_reports.py --markdown-only   # no LLM calls
uv run python chunk_and_embed.py --dry-run         # no embedding calls
```

## Incrementality

`../processed/manifest.json` records what ran under which parameters:

| Change | Re-runs |
| --- | --- |
| source file sha256 | everything from PDF → Markdown |
| `SCHEMA_VERSION` or `GEMINI_MODEL` | extract → chunk → embed → import |
| `CHUNK_*` or `GEMINI_EMBEDDING_MODEL` or `EMBEDDING_DIMENSIONS` | chunk → embed → import |
| nothing | file is skipped |

Deleting `manifest.json` forces a full reprocess on the next run.

## Tuning the chunker without spending anything

```powershell
uv run python chunk_and_embed.py --dry-run
```

Or directly, no credentials and no database needed:

```powershell
uv run python -c "from chunker import chunk_markdown; import pathlib; cs = chunk_markdown(pathlib.Path('../samples/sample_posudek.md').read_text(encoding='utf-8')); print(len(cs), [c.token_count for c in cs])"
```

## Notes

- `EMBEDDING_DIMENSIONS` is 1536. Gemini offers 128-3072 (recommended tiers
  768 / 1536 / 3072) but a pgvector HNSW index accepts at most 2000, so 3072 is
  not usable. Changing this also requires editing `vector(1536)` in
  `sql/tables/02_create_document_chunks.sql` and recreating the table.
- Chunks are embedded with `task_type=RETRIEVAL_DOCUMENT` and queries with
  `RETRIEVAL_QUERY`. Both sides must match or retrieval quality collapses.
- `tiktoken` sizes chunks locally and is not Gemini's tokenizer, so counts are
  approximate. The 800-token target leaves ample margin under the 2048-token
  input limit of `gemini-embedding-001`.
- Parquet is written per document. A new report costs one new file, not a full
  cache regeneration.
- `../processed/` is a reproducible cache. Regenerate it instead of editing it.
- Never commit reports or large datasets.
