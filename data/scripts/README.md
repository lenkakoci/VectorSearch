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
uv run python check_pipeline.py         # verify every stage; costs nothing
uv run python search_reports.py "dotaz" --hybrid
```

Adding reports has a gated procedure — convert and check for free before paying
for extraction and embeddings. See `.claude/skills/add-reports/SKILL.md`.

## Scripts

| Script | Role |
| --- | --- |
| `gemini_auth.py` | Gemini client construction, retry predicate, and L2 normalisation of embeddings. |
| `configure_postgresql.py` | Generic SQL runner over `sql/extensions/` and `sql/tables/`. Connects through `pipeline_common`. |
| `schemas.py` | Pydantic extraction schema, `SCHEMA_VERSION`, grounding prompt. |
| `manifest.py` | Pipeline state and stage-invalidation logic. |
| `pipeline_common.py` | Settings, paths, connection parameters, logging. |
| `chunker.py` | Section-aware Markdown chunker. No API, no database. |
| `search_filters.py` | `field:value` prefixes and metadata flags into a parameterised WHERE. No API, no database. |
| `markdown_normalizer.py` | Rebuilds headings and strips artefacts in extracted page text. `MARKDOWN_VERSION`. |
| `extract_reports.py` | PDF → page text (pdfminer) → normalise → LLM structured extraction. |
| `chunk_and_embed.py` | Chunking + embeddings → per-document parquet. |
| `import_reports.py` | JSON + parquet → PostgreSQL (upsert). |
| `ingest.py` | Incremental orchestrator. The usual entry point. |
| `check_pipeline.py` | Verifies each stage's artefacts. No API, writes nothing, exits 1 on failure. |
| `search_reports.py` | Vector and hybrid (RRF) search from the CLI. |

## Flags worth knowing

```powershell
uv run python ingest.py --dry-run             # show the plan, change nothing
uv run python ingest.py --only report.pdf     # one file
uv run python ingest.py --force               # redo everything
uv run python ingest.py --skip-import         # stop before the database

uv run python extract_reports.py --markdown-only   # no LLM calls
uv run python chunk_and_embed.py --dry-run         # no embedding calls

uv run python check_pipeline.py --no-db            # artefacts only
uv run python check_pipeline.py --only Roudno      # one document

uv run python search_reports.py "q" --mode fts     # full text only, no API call
uv run python search_reports.py "autor:Poul q"     # inline metadata filter
uv run python search_reports.py --list --obec Lednice
```

`--only` takes the stem, the file name or a path in every script (`Roudno`,
`Roudno.pdf`, `PDFs/Roudno.pdf`).

## Incrementality

`../processed/manifest.json` records what ran under which parameters:

| Change | Re-runs |
| --- | --- |
| source file sha256 | everything from PDF → Markdown |
| `MARKDOWN_VERSION` | markdown → extract → chunk → embed → import |
| `SCHEMA_VERSION` or `GEMINI_MODEL` | extract → chunk → embed → import |
| `CHUNK_*` or `GEMINI_EMBEDDING_MODEL` or `EMBEDDING_DIMENSIONS` | chunk → embed → import |
| a stage's output file is missing | that stage and everything after it |
| nothing | file is skipped |

Deleting `manifest.json` forces a full reprocess on the next run. Deleting part
of `../processed/` re-runs only the affected stages, which is the cheaper way to
force a rebuild.

Note the limit of the file check: a Markdown file that *exists but is wrong* is
not detected, only a missing one. `check_pipeline.py` covers that; to rebuild one
document use `extract_reports.py --markdown-only --force --only <stem>`.

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
- PDF text comes from pdfminer, one pass, page by page — that same pass produces
  `<stem>.pages.json`. `locate_pages()` matches chunk text against page text, so
  a second PDF library on either side breaks page attribution. Do not add one.
- Full text is indexed under two configurations at once, `czech` (hunspell
  morphology, stop words) and `czech_literal` (accent-stripped, verbatim), and
  queried with `websearch_to_tsquery` over both. The dictionary comes from
  `postgres/Dockerfile`; without it `03_create_czech_fts.sql` fails and the
  `simple` trigger from `02` stays, which is the previous working behaviour.
- Search filters are SQL, not a fourth engine: both branches already are SQL, so
  a restriction is more `WHERE`. `search_filters.py` composes that clause only
  from its own fixed vocabulary and passes every value as a `%s` parameter, so
  user text can never become syntax. Do not let a model write SQL here.
- With a metadata filter the vector query joins `documents` before sorting, so
  the top-N is taken *within* the filter rather than filtered afterwards. That
  costs the HNSW index — the planner sorts after the join — which is irrelevant
  at this corpus size and is the correct trade-off anyway: post-filtering a
  global top-N can return nothing. At scale, turn on pgvector's
  `hnsw.iterative_scan` rather than reordering the query.
- One search is one embedding request and the quota is per request per minute,
  so a burst of searches can hit 429. `embed_query()` retries like the ingestion
  calls do; `--mode fts` avoids the call entirely.
- `tiktoken` sizes chunks locally and is not Gemini's tokenizer, so counts are
  approximate. The 800-token target leaves ample margin under the 2048-token
  input limit of `gemini-embedding-001`.
- Parquet is written per document. A new report costs one new file, not a full
  cache regeneration.
- `../processed/` is a reproducible cache. Regenerate it instead of editing it.
- Never commit reports or large datasets.
