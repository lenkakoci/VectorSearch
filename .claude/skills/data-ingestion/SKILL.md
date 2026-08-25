---
name: data-ingestion
description: Use when working on report extraction, chunking, embedding, import, or evolving the extraction schema.
---

# Data Ingestion Skill

Load this skill when touching anything in `data/scripts/`.

## Stage map

| Stage | Script | Input | Output | Invalidated by |
| --- | --- | --- | --- | --- |
| markdown | `extract_reports.py` | `data/PDFs/*.pdf` | `processed/markdown/<stem>.md` | source sha256 |
| extract | `extract_reports.py` | cached Markdown | `processed/extracted/<stem>.json` | `SCHEMA_VERSION`, `GEMINI_MODEL` |
| chunk | `chunk_and_embed.py` | Markdown + extraction | `processed/chunks/<stem>.parquet` | chunk params, embedding model/dims |
| import | `import_reports.py` | JSON + parquet | `documents`, `document_chunks` | any of the above |

`ingest.py` diffs `processed/manifest.json` against the current config and runs
only the stale stages, cascading forward. Stages are also runnable standalone.

## Key files

- `schemas.py` — Pydantic extraction schema, `SCHEMA_VERSION`, and the grounding prompt.
- `manifest.py` — `stages_to_run()` holds the invalidation logic. Change carefully.
- `chunker.py` — pure function, no API or database. Testable without credentials.
- `pipeline_common.py` — settings, paths, connection params. Add config here, not per-script.
- `gemini_auth.py` — client construction, retry predicate, embedding normalisation.
- `configure_postgresql.py` — taken verbatim from the reference course project.
  **Do not modify**; re-copy if upstream changes.

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

## Chunking

Section-aware, from `chunker.py`: split on Markdown headings, window sections
over `CHUNK_MAX_TOKENS` with `CHUNK_OVERLAP_TOKENS`, merge sections under
`CHUNK_MIN_TOKENS`. The heading path becomes `section` and is the citation unit.

Tune without spending anything:
```powershell
uv run python chunk_and_embed.py --dry-run
```

`chunk_raw` is the verbatim text (cited to users, indexed for full-text search).
`chunk_text` is what was embedded and carries the Contextual Retrieval prefix
built from already-extracted metadata — no extra LLM call.

## Rules

- Never `TRUNCATE` or `DROP TABLE`. Reports are real data that accumulates.
- Parquet is per document, never one global file.
- Treat `data/processed/` as a regenerable cache; never hand-edit it.
- Never commit `data/PDFs/` contents.
