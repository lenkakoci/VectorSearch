# VectorSearch — sémantické vyhledávání v geologických posudcích

Interní pipeline, která z digitálních geologických posudků (PDF) vytáhne
strukturovaná metadata, rozdělí text na chunky, spočítá embeddingy a uloží vše do
PostgreSQL pro sémantické a hybridní vyhledávání.

```
PDF → Markdown → LLM strukturovaná extrakce → chunking → embedding → PostgreSQL
```

## Předpoklady

- Docker Desktop
- [uv](https://docs.astral.sh/uv/)
- API klíč pro Google Gemini — <https://aistudio.google.com/apikey>

## Quickstart

```powershell
# 1) PostgreSQL s pgvector
cd deploy\local
Copy-Item .env.template .env        # doplnit PGPASSWORD
docker compose up -d postgres
docker compose ps                   # počkat na healthy

# 2) Závislosti a konfigurace
cd ..\..\data\scripts
uv sync
Copy-Item .env.template .env        # doplnit GEMINI_API_KEY a PGPASSWORD

# 3) Schéma databáze (idempotentní, lze spouštět opakovaně)
uv run python configure_postgresql.py

# 4) Zpracování posudků
Copy-Item C:\cesta\k\posudku.pdf ..\PDFs\
uv run python ingest.py

# 5) Vyhledávání
uv run python search_reports.py "hladina podzemní vody" --hybrid
```

## Jak přidat nový posudek

Zkopírovat PDF do `data/PDFs/` a spustit:

```powershell
uv run python ingest.py
```

Pipeline je inkrementální — zpracuje jen nové nebo změněné soubory, ostatní
přeskočí. `--dry-run` ukáže plán bez provedení, `--force` přepočítá vše.

## Struktura

| Cesta | Obsah |
| --- | --- |
| `postgres/Dockerfile` | PostgreSQL 17 + pgvector |
| `deploy/local/` | Docker Compose pro lokální běh |
| `data/PDFs/` | Vstupní posudky — **negitované**, interní dokumenty |
| `data/samples/` | Testovací fixture pro ověření pipeline |
| `data/processed/` | Reprodukovatelná cache (Markdown, JSON, parquet, manifest) |
| `data/scripts/` | Pipeline skripty (uv-managed) |
| `CLAUDE.md`, `.claude/skills/` | Konfigurace pro Claude Code |

## Skripty

Spouštět z `data/scripts`.

| Skript | Účel |
| --- | --- |
| `configure_postgresql.py` | Aplikuje SQL z `sql/extensions/` a `sql/tables/` |
| `ingest.py` | Inkrementální pipeline — běžný vstupní bod |
| `extract_reports.py` | PDF → Markdown → strukturovaná extrakce |
| `chunk_and_embed.py` | Chunking + embeddingy → parquet |
| `import_reports.py` | Parquet + JSON → PostgreSQL |
| `search_reports.py` | Vyhledávání z příkazové řádky |

Užitečné přepínače:

```powershell
uv run python extract_reports.py --markdown-only   # konverze bez LLM volání
uv run python chunk_and_embed.py --dry-run         # ladění chunků bez placení
uv run python ingest.py --dry-run                  # co by se stalo
```

## Datový model

**`documents`** — jeden řádek na posudek. Typované sloupce tvoří stabilní jádro
(`title`, `locality`, `report_date`, `author`, `client`, `summary`); doménově
specifická pole žijí v `extraction_json JSONB`, dokud se schéma nedoladí podle
reálných posudků.

**`document_chunks`** — jeden řádek na chunk. `embedding vector(1536)` s HNSW
indexem pro cosine similarity, `fts_chunk tsvector` s GIN indexem pro full-text.
Citační jednotkou je `section` (cesta Markdown nadpisů), `page_from`/`page_to`
jsou best-effort a mohou být `NULL`.

## Stav

Infrastruktura, chunking, embedding, import i vyhledávání jsou hotové a ověřené.

Extrakční schéma v `data/scripts/schemas.py` je **provizorní** — vzniklo dřív, než
byly k dispozici reálné posudky. `report_type` je volný text, ne `Literal`, a pole
`extra_fields` sbírá vše, co schéma nepokrývá. Postup, jak z reálných posudků
odvodit finální schéma, je v `.claude/skills/data-ingestion/SKILL.md`.

## Bezpečnost

- Posudky jsou interní dokumenty organizace. `data/PDFs/` je gitignorovaný.
- Přihlašovací údaje patří do `.env`, verzují se jen `.env.template`.
- Extrakce je striktně groundovaná na text dokumentu — model nesmí nic domýšlet.
