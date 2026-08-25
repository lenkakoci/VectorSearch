---
name: local-runtime
description: Use for running the local Docker Compose PostgreSQL stack and executing the pipeline scripts in order.
---

# Local Runtime Skill

Load this skill when starting, stopping or debugging the local stack.

## Compose

Local Compose lives in `deploy/local`. One service: `postgres`, built from
`postgres/Dockerfile` (`pgvector/pgvector:pg17`).

```powershell
cd deploy\local
Copy-Item .env.template .env    # fill in PGPASSWORD
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
4. `uv run python search_reports.py "<dotaz>" --hybrid` to verify.

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
| Port 5432 already allocated | Another PostgreSQL container is running. |
| `GEMINI_API_KEY is required` | `data/scripts/.env` is missing credentials. |
| Nothing happens on ingest | Everything is up to date. Use `--dry-run` to see the plan, `--force` to override. |
