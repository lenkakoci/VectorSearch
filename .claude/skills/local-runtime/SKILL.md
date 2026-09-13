---
name: local-runtime
description: Use for running the local Docker Compose PostgreSQL stack and executing the pipeline scripts in order.
---

# Local Runtime Skill

Load this skill when starting, stopping or debugging the local stack.

## Compose

Local Compose lives in `deploy/local`. Three services: `postgres`, built from
`postgres/Dockerfile` (`pgvector/pgvector:pg17` plus the Czech hunspell
dictionary for full-text search), and the optional web demo, `api`
(`data/scripts/Dockerfile.api`, FastAPI on 127.0.0.1:8010, reads
`data/scripts/.env`) and `frontend` (`frontend/Dockerfile`, nginx on
127.0.0.1:3001 proxying `/api` to `api`). The pipeline needs only `postgres`.

The image is not just the base image, so after changing `postgres/Dockerfile` or
`postgres/tsearch_data/` run `docker compose build postgres` before `up`.

```powershell
cd deploy\local
if (-not (Test-Path .env)) { Copy-Item .env.template .env }   # then fill in PGPASSWORD
docker compose up -d postgres
docker compose ps               # wait for healthy
```

The compose file sets `name: vectorsearch` explicitly. Do not remove it — without
it Compose derives the project name from the parent directory (`local`), which
collides with any other project laid out the same way and makes Compose recycle
that project's containers.

Port 5432 is published on the host, so only one PostgreSQL project can run at a
time. Stop the other one before starting this.

## Startup order

1. `docker compose up -d postgres` from `deploy/local`
2. `uv run python configure_postgresql.py` from `data/scripts` — applies
   `sql/extensions/` then `sql/tables/` alphabetically. Safe to re-run: all DDL
   is `IF NOT EXISTS`.
3. `uv run python ingest.py` from `data/scripts` — extract, chunk, embed, import.
4. `uv run python check_pipeline.py` — verifies every stage. Costs nothing.
5. `uv run python search_reports.py "<dotaz>" --hybrid` to verify.
6. Web demo, optional: `docker compose up -d --build --no-deps api frontend`
   from `deploy/local` and open http://localhost:3001. Without `--no-deps`
   Compose rebuilds the postgres image as a dependency and, when the image
   changes, recreates the database container, dropping every open connection. Or without Docker:
   `uv run uvicorn search_api:app --reload --port 8010` from `data/scripts`
   and `npm run dev` from `frontend` (http://localhost:5173). Port 8010 can be
   held by only one of the two at a time.

Adding reports has its own gated procedure — see the `add-reports` skill. Do not
start with `ingest.py` on documents nobody has looked at.

## Safety

- Ask before starting or stopping services.
- **Never remove the `deploy/local/data/postgres` bind mount** without explicit
  approval. It holds the imported reports.
- Never pass `--remove-orphans` or `-v` to `docker compose down` without approval.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `no pg_hba.conf entry` / `database "geodb" does not exist` | Cluster init was interrupted. Stop the container, remove `deploy/local/data/postgres`, start again. Only safe when nothing has been imported yet. |
| `relation "documents" does not exist` | `configure_postgresql.py` has not run. |
| `text search configuration "czech" does not exist` | The image was not rebuilt, or `03_create_czech_fts.sql` failed. `docker compose build postgres`, then `configure_postgresql.py`. |
| Port 5432 already allocated | Another PostgreSQL container is running. |
| `GEMINI_API_KEY is required` | `data/scripts/.env` is missing credentials. |
| Nothing happens on ingest | Everything is up to date. Use `--dry-run` to see the plan, `--force` to override. |
