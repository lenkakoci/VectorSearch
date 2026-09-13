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
uv run uvicorn search_api:app --reload --port 8010   # API for the web demo
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
| `search_reports.py` | Vector, full-text and hybrid (RRF) search from the CLI. Argument parsing and printing only. |
| `search_service.py` | The search itself as a library: SQL for every branch, query embedding with a cache, RRF with per-branch ranks, `ts_headline` highlights, neighbours, facets. Takes a connection, returns dicts. |
| `search_api.py` | FastAPI over the service for the web demo (`frontend/`). Pydantic models, no search logic. Dependency group `api`, installed by default. |
| `text_match.py` | Loose text comparison (case, doubled spaces, kinds of dash) for golden-set evidence and later for quotes in answers. No API, no database. |
| `eval_retrieval.py` | Recall@k and MRR per search mode over `../eval/golden.yaml`, and the relevance gate when `rerank` runs. `--check` verifies the set against the database for free. |
| `rerank_service.py` | Grades search candidates 0-3 with Gemini (rubric, batches of 20, per-chunk cache), orders them by grade and applies the relevance gate. Model from `GEMINI_RERANK_MODEL`. |

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
uv run python search_reports.py "sonda" --kind annex --mode fts   # annex only
uv run python search_reports.py --list --obec Lednice
```

`--only` takes the stem, the file name or a path in every script (`Roudno`,
`Roudno.pdf`, `PDFs/Roudno.pdf`).

## Measuring retrieval

`../eval/golden.yaml` holds 40 Czech questions, each with the document and a
verbatim snippet of the chunk that answers it; six have no answer in the
corpus. `eval_retrieval.py` runs them through `fts`, `vector` and `hybrid` and
reports recall@5/10/40 and MRR, per question type, the rank of the first
relevant chunk per question, and what each mode still returns for the
unanswerable ones. JSON goes to `../processed/eval/`.

```powershell
uv run python eval_retrieval.py --check          # verify the set against the database; free
uv run python eval_retrieval.py                  # one query embedding per question
uv run python eval_retrieval.py --modes fts      # no API call
uv run python eval_retrieval.py --only opatov-gt4c --no-save
```

Relevance is decided by text, not chunk id - `text_match.py` ignores case,
doubled spaces and the kind of dash - so the set survives re-chunking. After
changing the corpus or the set, run `--check` first: a snippet that matches
nothing would otherwise count as a silent miss.

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
  calls do; `--mode fts` avoids the call entirely. `search_service.py` also keeps
  the last few hundred query embeddings in memory, so re-running a query with
  other filters or modes costs SQL only, and `compare()` embeds once for all
  three modes.
- Highlights and `lexical_match` come from `ts_headline` and `@@` in an outer
  query around the ranking, so they are computed only for the rows that survive
  `LIMIT`. `ts_headline` re-parses the chunk with the dictionary; on every
  candidate it would dominate the query time.
- `ts_headline` runs under the `czech` configuration only. A match found solely
  by the `czech_literal` branch (a query typed without diacritics against a word
  written with them) is returned but not highlighted.
- The API container (`Dockerfile.api`) pre-fetches the tiktoken encoding at build
  time: `chunker.py` loads it at import and `pipeline_common` imports `chunker`,
  so without that the container would need the network to start.
- Full text comes in two strengths. `fts` requires every word of the query
  (`websearch_to_tsquery` ANDs them): exact for a code, nearly useless for a
  question. `fts_any` and the candidates of `rerank` accept any word and rank
  by summed BM25-style IDF, because `ts_rank` has no notion of rarity; a place
  name then outweighs "podzemní voda". Stop words are dropped by asking the
  `czech` configuration, the only one with a stop list.
- The vector branch sets `hnsw.ef_search` to the number of rows it fetches,
  local to the transaction. Today the planner scans exactly and the setting is
  moot; once the index is used, a fetch above 40 would otherwise be cut to 40.
- `rerank` grades 40 candidates in two parallel calls of 20: a median of 6 s
  per query on the golden set, 4 to 13 s. Grades are cached per model, query
  and chunk for the life of the process, so the web page re-running a query
  with another filter pays only for chunks it has not graded yet.
- Grades are not fully reproducible even at temperature 0: the same chunk has
  been graded 2 in one process and 3 in another. A borderline chunk can cross
  the gate either way, so compare evaluation runs by their totals rather than
  by single questions.
- `tiktoken` sizes chunks locally and is not Gemini's tokenizer, so counts are
  approximate. The 800-token target leaves ample margin under the 2048-token
  input limit of `gemini-embedding-001`.
- Parquet is written per document. A new report costs one new file, not a full
  cache regeneration.
- `../processed/` is a reproducible cache. Regenerate it instead of editing it.
- Never commit reports or large datasets.
