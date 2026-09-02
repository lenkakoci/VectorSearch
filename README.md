# VectorSearch — sémantické vyhledávání v geologických posudcích

Interní pipeline, která z digitálních geologických posudků (PDF) vytáhne
strukturovaná metadata, rozdělí text na chunky, spočítá embeddingy a uloží vše do
PostgreSQL pro sémantické a hybridní vyhledávání.

```
PDF → Markdown → LLM strukturovaná extrakce → chunking → embedding → PostgreSQL
```

Vyhledávání je hybridní: vektorové (pgvector HNSW) a fulltextové s **českým
slovníkem**, takže dotaz `vrty` najde i dokument, který píše `vrtů`. Výsledky se
slučují přes Reciprocal Rank Fusion a citují se na úroveň sekce dokumentu.

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

Zkopírovat PDF do `data/PDFs/` a projít tímhle postupem. **Konverze a kontrola
jsou zdarma, extrakce a embeddingy stojí peníze** — proto se nejdřív dívá a
teprve pak platí.

```powershell
# 1) převod na Markdown, bez volání API
uv run python extract_reports.py --markdown-only

# 2) kontrola převodu, bez API i bez databáze
uv run python check_pipeline.py --no-db

# 3) teprve když je krok 2 čistý — placené fáze
uv run python ingest.py

# 4) plná kontrola včetně databáze
uv run python check_pipeline.py

# 5) zeptat se na něco, co umí zodpovědět jen nový posudek
uv run python search_reports.py "<termín z nového posudku>" --hybrid
```

Nahrávej po malých dávkách, ne dvacet souborů najednou — kroky 1 a 2 nic nestojí,
takže cena za to podívat se dřív je jen tvůj čas.

Pipeline je inkrementální: zpracuje jen nové nebo změněné soubory. Chybějící
soubor v `data/processed/` se počítá jako neaktuální, takže smazat část cache a
spustit `ingest.py` je legitimní způsob, jak si vynutit přepočet. `--dry-run`
ukáže plán bez provedení, `--force` přepočítá vše.

**Pozor na jednu mez:** poškozený (ale existující) Markdown pipeline sama
nepozná, kontroluje jen jeho přítomnost. Právě proto je v postupu krok 2.
Přegenerovat se dá přes `extract_reports.py --markdown-only --force --only <stem>`.

## Struktura

| Cesta | Obsah |
| --- | --- |
| `postgres/Dockerfile` | PostgreSQL 17 + pgvector + český hunspell slovník |
| `postgres/tsearch_data/` | Česká stopslova pro fulltext |
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
| `check_pipeline.py` | Kontrola všech fází u každého dokumentu |
| `search_reports.py` | Vyhledávání z příkazové řádky |

Užitečné přepínače:

```powershell
uv run python extract_reports.py --markdown-only   # konverze bez LLM volání
uv run python chunk_and_embed.py --dry-run         # ladění chunků bez placení
uv run python ingest.py --dry-run                  # co by se stalo
uv run python check_pipeline.py --no-db            # kontrola bez databáze
uv run python search_reports.py "dotaz" --mode fts # hledání bez volání API
```

`--only` bere ve všech skriptech stejné tvary — `Roudno`, `Roudno.pdf`
i `PDFs/Roudno.pdf`.

### Co kontroluje `check_pipeline.py`

Nic nezapisuje, nevolá API, nestojí nic. Návratový kód `1` při chybě. U každého
dokumentu ověří: počet nadpisů v Markdownu, zbytky po konverzi (obsah, tabulky,
paginace), mapu stránek, extrakci a její schéma, počet a velikost chunků, že
**každý** chunk má sekci, podíl chunků s číslem stránky, dimenze embeddingů,
shodu s databází, naplněný fulltextový index a nakonec zkusí slova ze středu
dokumentu opravdu vyhledat.

## Datový model

**`documents`** — jeden řádek na posudek. Typované sloupce tvoří stabilní jádro
(`title`, `locality`, `report_date`, `author`, `client`, `summary`); doménově
specifická pole žijí v `extraction_json JSONB`, dokud se schéma nedoladí podle
reálných posudků.

**`document_chunks`** — jeden řádek na chunk. `embedding vector(1536)` s HNSW
indexem pro cosine similarity, `fts_chunk tsvector` s GIN indexem pro full-text.
Citační jednotkou je `section` (cesta Markdown nadpisů), `page_from`/`page_to`
jsou best-effort a mohou být `NULL`.

## Vyhledávání

Tři režimy. **`fts` nevolá žádné API** — nic nestojí, nepodléhá kvótě a funguje
i bez Gemini klíče.

```powershell
uv run python search_reports.py "hladina podzemní vody"              # vektorový (výchozí)
uv run python search_reports.py "ČSN 75 9010" --mode fts             # jen fulltext, zdarma
uv run python search_reports.py "hladina podzemní vody" --mode hybrid # obojí, sloučené přes RRF
```

Skóre se liší podle režimu: `vector` ukazuje kosinovou podobnost (0–1),
`fts` hodnotu `ts_rank`, `hybrid` skóre RRF (~0,016–0,033).

### Filtrování podle metadat

Filtr a sémantiku lze **odlišit v jednom dotazu**. Prefixy se vyzobou z textu,
zbytek jde na vektory a fulltext:

```powershell
uv run python search_reports.py "autor:Poul obec:Lednice hladina vody" --mode hybrid
```
```
Hybridni vyhledavani: 'hladina vody'
  filtr: autor ~ 'Poul', obec ~ 'Lednice'
```

Totéž jde přepínači, což je vhodnější pro skriptování:

```powershell
uv run python search_reports.py "hladina vody" --autor Poul --obec Lednice --mode hybrid
```

| prefix | přepínač | filtruje |
| --- | --- | --- |
| `autor:` | `--autor` | autor posudku |
| `klient:` | `--klient` | objednatel |
| `lokalita:` | `--lokalita` | popis lokality |
| `obec:` | `--obec` | obec |
| `typ:` | `--typ` | typ průzkumu |
| `org:` | `--org` | zpracovatelská organizace |
| `od:` / `do:` | `--od` / `--do` | rozsah dat (`2019`, `2019-09`, `2019-09-11`) |
| `doc:` | `--document` | konkrétní UUID, lze opakovat |

Textové filtry hledají podřetězec, takže `autor:Poul` trefí i
`Mgr. Josefína Bízová, RNDr. Mgr. Ivan Poul, Ph.D.`. Hodnotu s mezerou dej do
uvozovek: `autor:"Ivan Poul"`. Neznámý prefix se nezahodí — zůstane součástí
hledaného textu a vypíše se varování.

### Přehled dokumentů

`--list` vypíše dokumenty odpovídající filtru, bez hledání v obsahu a bez API:

```powershell
uv run python search_reports.py --list
uv run python search_reports.py --list --obec Lednice
uv run python search_reports.py --list --od 2019 --do 2020
```

### Co vyhledávání nedělá

Vrací **pasáže, ne odpovědi** — úryvky seřazené podle relevance s citací sekce a
strany. Odpověď si přečteš v nich.

Neagreguje. Na otázky typu „kolik posudků je od UNIGEO" nebo „které zmiňují
třídu těžitelnosti" je nástrojem SQL nad `documents`, ne vyhledávání. Dotaz
uživatele se **záměrně nepřevádí na SQL modelem**: model si může vymyslet
sloupec nebo vrátit věcně špatný výsledek bez chyby, a u geologických posudků je
tichá chyba bezpečnostní problém — ze stejného důvodu má extrakce zakázáno
cokoli odvozovat.

## Český fulltext

PostgreSQL nemá český stemmer, takže konfigurace `simple` neuměla skloňování —
sekce „Technické parametry **vrtů** pro tepelné čerpadlo" se nedala najít dotazem
„**vrty** pro tepelné čerpadlo". Obraz proto doinstalovává slovník `hunspell-cs`
a `sql/tables/03_create_czech_fts.sql` z něj staví dvě konfigurace:

| konfigurace | co dělá |
| --- | --- |
| `czech` | morfologie a stopslova; `vrtů` i `vrty` → `vrt`, předložka `pro` vypadne |
| `czech_literal` | původní chování: odstranit diakritiku, indexovat doslovně |

Chunky se indexují **oběma** najednou a dotaz se přes OR ptá obou. Samotná
morfologie by totiž nenašla dotaz psaný bez diakritiky, a odháčkovat samotný
slovník nejde — kolabuje to 12 000 z jeho 261 000 hesel. Takhle neztrácíš nic,
co fungovalo dřív, jen přibývá skloňování.

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
