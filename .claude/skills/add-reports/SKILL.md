---
name: add-reports
description: Use when new report PDFs need to go into the corpus - adding, ingesting or re-processing documents, and verifying that a document came through the pipeline correctly.
---

# Adding Reports Skill

The recurring operational task: new PDFs arrive, get them into the database
without paying for a bad conversion and without silently importing a document
that lost its structure.

For how the machinery works see `data-ingestion`; for the stack itself see
`local-runtime`. This skill is the procedure.

## Why it is gated

Two of the four stages cost money (extraction and embeddings) and the two that
do not are exactly the ones that decide whether the result is any good. Converting
and checking first is free, so never start with `ingest.py` on documents nobody
has looked at.

The failure that matters is quiet. An unreadable PDF is loud - it logs an error
and skips. A report whose headings were never recognised imports perfectly, and
just has no section citation for the rest of its life.

## Procedure

```powershell
# 1. Drop the PDFs into data/PDFs/, then from data/scripts:

# 2. Convert only - no API calls, costs nothing
uv run python extract_reports.py --markdown-only

# 3. Verify the conversion - no API calls, no database needed
uv run python check_pipeline.py --no-db

# 4. Only once step 3 is clean: the paid stages
uv run python ingest.py

# 5. Full verification, now including the database
uv run python check_pipeline.py

# 6. Ask the corpus something only the new report can answer
uv run python search_reports.py "<term from the new report>" --hybrid
```

Work in small batches, not twenty files at once. Steps 2 and 3 are free, so the
cost of looking first is only your time, and the manifest makes sure nothing is
redone.

## Reading step 2

One line per document:

```
23 headings (toc) | unwrapped 0 table rows | dropped 35 furniture, 35 contents lines
```

| field | expect | worry when |
| --- | --- | --- |
| `headings` | the report's own heading count, plus one for the title | `0`, or far fewer than the contents page lists |
| source in brackets | `toc` | `heuristic` means no contents page was found - check the result. `none` means nothing was recovered |
| `furniture` | roughly one to three times the page count | `0` on a report that clearly has a running header |
| `unwrapped` | `0` | anything else is odd; pdfminer does not produce tables |

## Reading step 3 and 5

`check_pipeline.py` prints OK / VAROVÁNÍ / CHYBA per check per document and exits
1 if anything failed. What the failures mean:

| check | CHYBA means | do |
| --- | --- | --- |
| `markdown` | no headings at all | see the diagnosis table below |
| `sekce` | some chunk has no `section` | headings are partial; fix before importing |
| `extrakce` | JSON missing or title empty | re-run `extract_reports.py` |
| `chunky` | parquet missing | re-run `chunk_and_embed.py` |
| `embeddingy` | wrong dimensionality | `EMBEDDING_DIMENSIONS` changed without re-embedding |
| `databáze` | not imported, or count differs from the parquet | re-run `import_reports.py` |
| `fulltext test` | words from the document do not find it | the Czech configuration is missing (`03_create_czech_fts.sql`) or the trigger never fired |
| `zbytky konverze` | (warning) contents, table rows or repeated lines survived | the normaliser did not recognise them; usually the headings are wrong too |
| `stránky` | (warning) under 80% of chunks have a page | the Markdown and the page map drifted apart |

## Diagnosis: no or missing headings

The normaliser reconstructs structure from what survived in the text. These are
its assumptions, in the order they are worth checking:

| assumption | when it does not hold |
| --- | --- |
| the PDF has a text layer | a scan without OCR yields nothing - `ERROR: Empty Markdown extracted` |
| there is a contents page with dot leaders (`1.2. NAME ...... 5`) | falls back to the heuristic below |
| without one: numbering is continuous from 1 | no headings recovered, warning logged |
| headings are numbered at all | an unnumbered "Závěr" in bold is never recognised |
| body and contents wording agree to ~85% | that heading is not promoted |
| running header/footer repeats on at least half the pages | it stays in the text and pollutes every chunk |
| that repeated line is under 80 characters | a long footer is not removed |
| a line repeating on most pages is not content | **it gets deleted as pagination** - the one failure with no warning |

The last one is the only silent one. The 25% text-loss guard is what stands
behind it: lose more than that and the raw conversion is kept instead.

If a new kind of report breaks the rules structurally - unnumbered headings, a
contents page laid out as a table - that is a normaliser change, not something to
work around per document. Bump `MARKDOWN_VERSION` when you make one.

## Re-processing

`processed/` is a cache. Deleting part of it to force a rebuild is fine -
`ingest.py` notices missing artefacts and redoes exactly those stages:

```powershell
Remove-Item ..\processed\extracted\Roudno.json, ..\processed\chunks\Roudno.parquet
uv run python ingest.py
```

`--force` also works but redoes documents that were fine, and pays for them again.

One trap: a Markdown file that exists but is *wrong* is not detected by the
pipeline - only its absence is. `check_pipeline.py` is what covers that, which is
why step 3 exists. To rebuild it: `extract_reports.py --markdown-only --force --only <stem>`.

`--only` accepts the stem, the file name or a path (`Roudno`, `Roudno.pdf`,
`PDFs/Roudno.pdf`) in every script.

## Rules

- Never run the paid stages on a document whose Markdown nobody has looked at.
- Never commit `data/PDFs/` contents.
- Do not hand-edit `data/processed/`; regenerate it.
