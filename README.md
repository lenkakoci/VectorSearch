# VectorSearch — sémantické vyhledávání v geologických posudcích

Interní pipeline, která z digitálních geologických posudků (PDF) vytáhne
strukturovaná metadata, rozdělí text na chunky, spočítá embeddingy a uloží vše do
PostgreSQL pro sémantické a hybridní vyhledávání. Nad hledáním stojí druhý
režim, který z nalezených úryvků složí odpověď a u každé věty nechá zdroj.

```
PDF → Markdown → LLM strukturovaná extrakce → chunking → embedding → PostgreSQL

dotaz → fulltext + vektor → reranking → brána relevance → kontext → odpověď
                                                                    s ověřenými citacemi
```

Vyhledávání je hybridní: vektorové (pgvector HNSW) a fulltextové s **českým
slovníkem**, takže dotaz `vrty` najde i dokument, který píše `vrtů`. Výsledky se
slučují přes Reciprocal Rank Fusion a citují se na úroveň sekce dokumentu.
Odpověď smí říct jen to, co je ve zdrojích, a server u každé věty ověřuje
doslovný citát i čísla.

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

# 6) Webové demo (API + React), podrobně v sekci „Webové rozhraní"
uv run uvicorn search_api:app --reload --port 8010
cd ..\..\frontend; npm install; npm run dev        # http://localhost:5173
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
| `data/eval/` | Zlatá sada otázek pro měření vyhledávání |
| `data/scripts/` | Pipeline skripty (uv-managed), vyhledávací služba a její API |
| `frontend/` | Webové demo vyhledávání (React + Vite + Tailwind) |
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
| `search_service.py` | Vyhledávací logika jako knihovna (SQL, embedding, RRF, kontext, facety); volá ji CLI i API |
| `search_api.py` | FastAPI nad službou pro webové demo (`uv run uvicorn search_api:app --port 8010`) |
| `eval_retrieval.py` | Měření kvality vyhledávání nad zlatou sadou: recall@k a MRR pro každý režim |
| `ask_reports.py` | Odpověď s citacemi z příkazové řádky |
| `answer_service.py` | Celý řetěz odpovědi: kandidáti, brána, kontext, model, kontrola citací |
| `eval_answers.py` | Měření kvality odpovědí nad zlatou sadou |

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

Navíc hledá v chunkách věty, které mluví k modelu, ne ke čtenáři: „ignoruj
předchozí pokyny", přidělení role, diktovanou odpověď nebo napodobený systémový
prompt, česky i anglicky. Do promptu jdou zdroje jako data, takže tohle není
obrana, ale jediné místo, kde se člověk dozví, že taková věta v korpusu je.
Pravidla jsou schválně úzká: běžné „podle metodického pokynu MŽP" nebo „podle
pokynů objednatele" mlčí, protože hlásí se až sloveso rušící dřívější zadání.
Dnes je všech 16 dokumentů čistých.

`--triage` vypíše jen to, co potřebuje rozhodnutí, seskupené podle toho, co s tím
dělat. `--removed` ukáže, co normalizátor z dokumentu smazal a podle jakého
pravidla:

```powershell
uv run python check_pipeline.py --removed --only Roudno
```
```
Roudno  -  odstraněno 67 řádků

  ZÁHLAVÍ/PATIČKA  (32 řádků)
        32x  Roudno - rekreační areál (práh 9)

  OBSAH  (35 řádků)
        35x  23 položek od 'Úvod'
```

Mazání opakovaných řádků je jediný krok, který může vzít skutečný obsah, aniž by
to dál kdokoli poznal — proto je jako jediný takhle rozepsaný. Když by mazání
sebralo víc než čtvrtinu textu, normalizátor ho zopakuje **bez mazání záhlaví**,
aby nepřišel o nadpisy; zbylé záhlaví se pak ohlásí jako `zbytky konverze`.

## Datový model

**`documents`** — jeden řádek na posudek. Typované sloupce tvoří stabilní jádro
(`title`, `locality`, `report_date`, `author`, `client`, `summary`); doménově
specifická pole žijí v `extraction_json JSONB`, dokud se schéma nedoladí podle
reálných posudků.

**`document_chunks`** — jeden řádek na chunk. `embedding vector(1536)` s HNSW
indexem pro cosine similarity, `fts_chunk tsvector` s GIN indexem pro full-text.
Citační jednotkou je `section` (cesta Markdown nadpisů), `page_from`/`page_to`
jsou best-effort a mohou být `NULL`. `content_kind` je `prose` nebo `annex`;
přílohové chunky mají `embedding IS NULL` a jsou dohledatelné jen fulltextem.

## Jak vzniká struktura

PDF extraktor vrací holý text bez písem a stylů, takže **nadpis od odstavce
nepozná**. Bez rekonstrukce by byl posudek jeden blok, chunker by spadl na jednu
bezejmennou sekci a každý chunk by přišel o citaci. Tahle kapitola popisuje, jak
se struktura skládá zpátky — a kde to může selhat.

Všechno tady běží **bez API a bez databáze**, takže se to dá ladit zdarma:

```powershell
uv run python extract_reports.py --markdown-only   # převod a normalizace
uv run python check_pipeline.py --no-db --triage   # co potřebuje rozhodnutí
uv run python check_pipeline.py --removed          # co se smazalo a proč
uv run python chunk_and_embed.py --dry-run         # chunky bez embeddingů
```

### 1. Klasifikace stránek

[page_classifier.py](data/scripts/page_classifier.py) označí každou stranu jako
`prose`, `form` nebo `empty` ze dvou čísel:

| signál | co měří | práh |
| --- | --- | ---: |
| podíl dlouhých řádků | souvislý text se láme až na okraji (≥ 45 znaků), buňka formuláře má dvě slova | < 12 % |
| podíl funkčních slov | česká věta se neobejde bez `je`, `se`, `byl`, `nebo`; tabulka je nemá | < 6 % |

**Formulář je jen strana, kde jsou nízko obě.** Ta konjunkce je celá pointa:
vrtné protokoly mají funkčních slov ~1 %, méně než laboratorní formuláře, ale
jejich litologické popisy jsou souvislé věty, takže je zachrání dlouhé řádky.
Pravidlo na slovech samotné by zahodilo přesně to, co lidi hledají.

Do seznamu **nepatří předložky**. `od`, `do`, `po`, `na` používá formulář
v popiscích stejně jako próza — samotné `od - do:` drželo 93 vrtných protokolů
nad prahem. Co formulář nemá, je sloveso.

Doplňková pravidla: běh kratší než 2 strany se pohltí okolím (tabulka uvnitř
kapitoly patří ke kapitole), prázdné strany běh nepřerušují (sken uprostřed
přílohy ji nerozdělí) a **úvodní běh až 3 stran je obálka, ne příloha** —
titulní strana je krátkořádková a beze sloves, takže se jinak měří jako formulář.

Výsledek jde do `processed/markdown/<stem>.pagekind.json`, pozičně shodného
s `pages.json`. Zvlášť schválně: `locate_pages()` čte `pages.json` jako holý
seznam řetězců a na tom kontraktu stojí dohledání stránek.

### 2. Normalizér — pravidla v pořadí

[markdown_normalizer.py](data/scripts/markdown_normalizer.py), kroky jsou
závislé na pořadí:

1. **Odsazení přílohy.** Formulářové strany a všechno za hranicí přílohy se
   odloží stranou a připojí na konec pod `## Přílohy`. Teprve pak běží zbytek —
   práh na záhlaví i pojistka ztráty tak vidí jen tělo zprávy, na což byly
   kalibrované.
2. **Rozbalení layoutových tabulek.** Blok `|`-řádků s méně než 60 % vyplněných
   buněk je sloupcový layout, ne data.
3. **Mazání záhlaví a patiček.** Řádek do 160 znaků opakovaný na **polovině
   stran** (minimálně 3×) je paginace. Signatura musí obsahovat **slovo o třech
   písmenech** — jinak by se mazaly laboratorní hodnoty jako `<0,` nebo `207.`
4. **Vytažení obsahu.** Položka je `číslo … tečky … strana` (≥ 4 tečky),
   potřeba jsou aspoň 3. Položky dál než 40 řádků od sebe tvoří **samostatné
   bloky** a každý se maže zvlášť.
5. **Povýšení nadpisů** podle obsahu: `1.` → `##`, `1.1` → `###`, hloubka max 4.
   Párování je fuzzy (85 % podobnosti), protože extraktor vynechává glyfy.
   Doplňkově se dohledají čísla oddělená od názvu a podsekce, které mělký obsah
   nelistuje (podle rodiče, rozsahu a pořadí mezi sourozenci).
6. **Titulek dokumentu.** Odmítne se osoba, firma, adresa, kontakt a položka
   seznamu; z toho, co zbude, vyhraje řádek pojmenovávající druh zprávy. **Když
   žádný takový není, nepovýší se nic** — špatný titulek je horší než žádný,
   protože stojí v kořeni každé citace.
7. **Pojistka ztráty.** Když by normalizace zahodila víc než **25 %** písmen
   a číslic, zopakuje se **bez mazání záhlaví**; teprve pak se vrátí surový text.

### 3. Hranice přílohy

Formulářové strany nejsou celá příloha. Vrtné protokoly jsou próza podle všech
měřítek, ale leží za poslední kapitolou — a bez hranice zdědí její nadpis.

> **Hranice = první formulářová strana za poslední stranou, která nese číslovaný
> nadpis uvedený v obsahu.**

Požadavek „uvedený v obsahu" je nutný: bez něj se za nadpis počítá věta
začínající číslem (*„4 EO (ekvivalentní obyvatele) z každé projektované
stavby RD"*) a hranice přeskočí přílohu celou.

Pravidlo drží pro běžný posudek (příloha následuje po poslední kapitole)
i pro **svazek** více zpráv v jednom PDF, kde dílčí zprávy číslují až do konce
a hranice proto padne pozdě, místo aby jejich strukturu spolkla.

### 4. Chunker

[chunker.py](data/scripts/chunker.py) je čistá funkce — žádné API, žádná
databáze, testovatelná bez přihlašovacích údajů.

1. **Dělení podle nadpisů.** Cesta nadpisů (`Kapitola > Podkapitola`) se stane
   `section` a je citační jednotkou.
2. **Okna přes velké sekce.** Nad `CHUNK_MAX_TOKENS` (800) se sekce dělí
   přednostně na hranicích odstavců, s překryvem `CHUNK_OVERLAP_TOKENS` (100).
   Když je překryv celých odstavců nedosažitelný, uřízne se **konec posledního
   odstavce** — dřív v takovém případě nevznikl překryv žádný.
3. **Nadpis do každého okna**, ne jen do prvního. `fts_chunk` se staví
   z `chunk_raw`, takže jinak nešlo najít pokračování dlouhé sekce podle názvu.
4. **Slučování malých sekcí jen uvnitř stejné sekce.** Slučování přes hranici
   nadpisu dřív nechávalo popisek toho předchozího, takže malá sekce byla
   citována jako ta nad ní.
5. **Limit se vynucuje** po spojení, ne po odstavcích — separátory se dřív
   nepočítaly a chunky limit přerůstaly.

### 5. `content_kind` — popisek zvlášť, cena zvlášť

Dvě nezávislé otázky se dvěma nezávislými zdroji:

| otázka | rozhoduje | kde |
| --- | --- | --- |
| Jak to citovat? | **pozice** v dokumentu | normalizér vloží `## Přílohy` |
| Platit za embedding? | **typ stránky** | `content_kind` z `pagekind.json` |

Proto mají vrtné popisy citaci `… > Přílohy` (pravdivou) **a zároveň vektor**
(protože jsou to prózou). Kdyby obojí viselo na jednom signálu, jedno by se
ztratilo. Chunk, jehož stránku se nepodařilo dohledat (~4 %), se počítá jako
próza — nedohledaná strana stojí embedding navíc, ale nevyrobí díru v indexu.

### 6. Záludnosti — kde to může klasifikovat nebo nachunkovat špatně

| co | proč se to stane | jak se to projeví | co s tím |
| --- | --- | --- | --- |
| **Prahy jsou naladěné na 15 posudků** | 12 % / 6 % dělí tenhle korpus čistě (zdravé 0–8,8 %, problémové 28,5–79,5 %), ne korpus obecně | posudek od jiného zpracovatele může mít prózu označenou jako formulář nebo naopak | `check_pipeline --triage`, sloupec „přílohy"; prahy jsou konstanty v `page_classifier.py` |
| **Titulní strana vypadá jako formulář** | krátké řádky, žádná slovesa | obálka spadne do přílohy a odnese s sebou dobrý titulek | ošetřeno pravidlem „úvodní běh do 3 stran je obálka" — **delší obálka ho obejde** |
| **Vrtný protokol je hraniční případ** | funkčních slov ~1 %, drží ho jen dlouhé řádky | při zpřísnění prahu dlouhých řádků zmizí nejcennější text z vektorů | před změnou prahu ověřit dokument s `DOKUMENTACE SONDY` |
| **Svazek více zpráv v jednom PDF** | `outline` slučuje všechny obsahy do jednoho (první název pro dané číslo vyhraje) | z 51 položek zbude 9 na 265 stran; nadpis dílčí zprávy přistane uvnitř přílohy | známé, neřešené — rozpad svazků je samostatný úkol |
| **Práh na záhlaví škáluje s počtem stran** | `polovina stran`, ale opakování pochází z přílohy | stejná příloha smaže 12 000 řádků u dlouhého dokumentu a nic u krátkého | ošetřeno odsazením přílohy před měřením |
| **Pojistka ztráty je pořád schod** | při překročení se zahodí celá normalizace včetně správně nalezených nadpisů | dokument bez jediného nadpisu a se všemi chunky bez citace | odstupňováno (zopakuje se bez mazání záhlaví), ale druhá úroveň zůstává vše-nebo-nic |
| **Příloha bez jediné formulářové strany** | hranice se hledá jako *formulářová* strana za posledním nadpisem | prozaická příloha zdědí poslední kapitolu (`6.1 SEZNAM NOREM`) | známé, neřešené |
| **`tiktoken` počítá češtinu níž než Gemini** | jiný tokenizér, rozdíl 10–30 % | chunk může být u modelu větší, než se změřilo | cíl 800 proti limitu 2048 to pokrývá; při zvyšování `CHUNK_MAX_TOKENS` pozor |
| **Prefix `KONTEXT:` se nezapočítává** | přidává ~250 tokenů, ale `token_count` měří text bez něj | skutečný vstup do modelu je větší, než říká sloupec | varování při > 1500 tokenech; při ladění velikosti počítat s rezervou |
| **Malé sekce zůstávají malé** | slučuje se jen uvnitř stejné sekce | chunky o 32 tokenech | záměr — správný popisek je cennější než velikost; `check_pipeline` to hlásí |
| **Nedohledaná stránka** | `locate_pages` porovnává prvních 60 znaků proti textu strany | ~4 % chunků bez čísla strany, počítají se jako próza | citace bez strany, embedding navíc |

## Vyhledávání

Čtyři režimy. **`fts` nevolá žádné API** — nic nestojí, nepodléhá kvótě a funguje
i bez Gemini klíče.

```powershell
uv run python search_reports.py "hladina podzemní vody"              # vektorový (výchozí)
uv run python search_reports.py "ČSN 75 9010" --mode fts             # jen fulltext, zdarma
uv run python search_reports.py "hladina podzemní vody" --mode hybrid # obojí, sloučené přes RRF
uv run python search_reports.py "Jak hluboko je voda v Lednici?" --mode rerank  # s rerankingem
```

Skóre se liší podle režimu: `vector` ukazuje kosinovou podobnost (0–1),
`fts` hodnotu `ts_rank`, `hybrid` skóre RRF (~0,016–0,033) a `rerank` známku 0–3.

**Reranking** vezme 40 kandidátů, po dvaceti nejlepších z vektoru a z volnějšího
fulltextu, který nevyžaduje všechna slova dotazu. Model Gemini každému dá známku
podle toho, jak odpovídá na otázku: 3 přímo obsahuje odpověď, 2 obsahuje její
část, 1 jen souvisí s tématem, 0 nesouvisí. Výsledky se seřadí podle známky, při
shodě rozhoduje pořadí RRF. Známka 2 je zároveň brána relevance pro budoucí
generované odpovědi: co jí nedosáhne, do odpovědi nepůjde. Kandidáti se neberou
z prvních 40 po RRF, protože fúze vytlačí úryvky, které najde jen jedna větev,
typicky přílohy bez vektoru. Známky si běžící proces pamatuje pro dvojici dotaz
a chunk, takže opakovaný dotaz s jiným filtrem neplatí znovu. Model nastavuje
`GEMINI_RERANK_MODEL`, výchozí je `GEMINI_MODEL`.

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
| `druh:` | `--kind` | část zprávy: `prose` (tělo) nebo `annex` (přílohy; bez vektoru, najde je jen fulltext) |

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

Vrací **pasáže, ne odpovědi** — úryvky seřazené podle relevance s citací sekce
a strany. Odpověď z nich složí až druhý režim, popsaný v sekci
[Odpovědi s citacemi](#odpovědi-s-citacemi), a taky jen z nich.

Neagreguje. Na otázky typu „kolik posudků je od UNIGEO" nebo „které zmiňují
třídu těžitelnosti" je nástrojem SQL nad `documents`, ne vyhledávání. Dotaz
uživatele se **záměrně nepřevádí na SQL modelem**: model si může vymyslet
sloupec nebo vrátit věcně špatný výsledek bez chyby, a u geologických posudků je
tichá chyba bezpečnostní problém — ze stejného důvodu má extrakce zakázáno
cokoli odvozovat.

## Webové rozhraní

Dvě záložky nad stejnými filtry: **Vyhledávání** ukáže rozdíl mezi hledáním
podle slov a podle významu, **Zeptat se dokumentů** složí z nalezených úryvků
odpověď a u každé věty nechá zdroj. Stejná logika jako v CLI:
`search_service.py` volá `search_reports.py` i `search_api.py`, `answer_service.py`
pak `ask_reports.py` i `/api/answer`, nic se neduplikuje.

```
frontend/ (React, port 5173 / v Dockeru 3001)
   │  /api  (Vite proxy nebo nginx)
data/scripts/search_api.py  (FastAPI, port 8010)
   │
data/scripts/search_service.py  →  PostgreSQL
```

Lokálně, ve dvou terminálech:

```powershell
cd data\scripts;  uv run uvicorn search_api:app --reload --port 8010
cd frontend;      npm install; npm run dev        # http://localhost:5173
```

V Dockeru vedle databáze (obrazy se staví z `data/scripts/Dockerfile.api`
a `frontend/Dockerfile`; API čte `data/scripts/.env`, má připojený adresář
`data/processed/answers`, kam píše log otázek a cache odpovědí, a `data/PDFs`
jen pro čtení, aby mohlo posílat zdrojová PDF):

```powershell
cd deploy\local
docker compose up -d --build --no-deps api frontend   # http://localhost:3001
```

`--no-deps` je nutné. Bez něj Compose přestaví i obraz PostgreSQL, a pokud se
obraz změní, vytvoří databázový kontejner znovu. Data na připojeném disku
přežijí, ale všechna otevřená spojení spadnou.

Co stránka umí:

- **Režimy** Fulltext / Sémantické / Hybridní / Reranking / **Porovnat** –
  poslední spustí jeden dotaz v několika režimech vedle sebe s jedním
  embeddingem. Úryvek, který se objeví ve více sloupcích, dostane stejné
  písmeno; z toho je na první pohled vidět, co našla jen slova, co jen význam
  a co obojí. Zaškrtnutí „+ reranking“ přidá čtvrtý sloupec: 40 kandidátů
  ohodnocených Gemini známkou 0–3, s důvodem u každé karty a čarou pod prahem
  relevance. Stojí jedno až dvě volání API na dotaz, proto je ve výchozím stavu
  vypnuté.
- **Odznaky** u každého výsledku: `slova` / `význam` / `obojí`, `bez shody slov`
  (sémantický výsledek, ve kterém není žádné hledané slovo), `příloha`.
- **Zvýraznění** hledaných slov dělá PostgreSQL (`ts_headline` s konfigurací
  `czech`), takže se zvýrazní i skloněný tvar: dotaz `vrty` označí `vrtů`.
- **Upřesnit hledání**: autor, organizace, obec, klient, typ, dokument (výběr
  více hodnot s počty), období, část zprávy (tělo / přílohy). Každý filtr má
  vypínač, výběr se při vypnutí neztratí. Inline prefixy v dotazu fungují také.
- **Karta výsledku**: název, cesta sekce, strana, chunk, skóre, celý text,
  kontext ±1 chunk (sousedé v pořadí dokumentu), metadata dokumentu, rozpis
  „proč nalezeno" (pořadí a skóre v každé větvi, dosazený vzorec RRF) a odkaz
  „PDF, s. X", který otevře zdrojový posudek rovnou na té straně.
- **Expert / debug** (sbalený): požadavek, lexémy `tsquery` v obou
  konfiguracích, SQL a parametry filtrů, časy, počty kandidátů, tabulka
  pořadí × skóre.

Záložka **Zeptat se dokumentů** k tomu přidává:

- **Odpověď se stavem**: Odpovězeno, Částečně, Nedostatek podkladů, nebo
  Bez podkladů, když branou relevance neprošel žádný kandidát a model se vůbec
  nevolal. Pod odpovědí je souhrn „ověřeno X z Y vět“.
- **Citace u každé věty**: číslo zdroje jako tlačítko. Klik sjede na kartu
  zdroje a zvýrazní v ní citát, který server ověřil. Věta, která kontrolou
  neprošla, je podtržená vlnovkou s vysvětlením proč.
- **Zdroje**: citované rozbalené, ostatní sbalené. Karta nese známku od
  rerankeru, roli (`nalezeno`, `kontext`, `pod prahem`), sekci, stranu, chunk,
  metadata, kontext ±1, údaje o dokumentu a odkaz „PDF, s. X" na tu stranu
  zdrojového posudku.
- **Ve zdrojích chybí** a **Rozpory mezi zdroji**, když je model vyplní.
- **Expert: průběh odpovědi** (sbalený): kroky Dotaz → Fulltext → Vektor →
  Výběr kandidátů → Reranking → Brána → Kontext → Odpověď → Kontrola s počty
  a časy, k tomu přesný prompt a surová odpověď modelu před kontrolou.
- **Průběh místo čekání**: dokud odpověď vzniká, stránka vypisuje kroky, jak
  je server hlásí — kolik kandidátů dostalo známku, kolik jich prošlo branou,
  kolik zdrojů a tokenů má kontext, že model píše a kolik vět prošlo kontrolou.
  Jde o server-sent events z `POST /api/answer/stream`; když streamování
  neprojde, stránka se vrátí k obyčejnému `POST /api/answer`.
- **Nastavení**: počet zdrojů, minimální známka, sousední úryvky a „nová
  odpověď". Změna filtru odpověď nepřegeneruje — každá odpověď stojí volání
  modelu. Odpověď, která přišla z cache, je označená odznakem „z cache" a
  v expert panelu je vidět, že se model nevolal.

Ukázkové dotazy jsou v poli jako tlačítka: `hladina podzemní vody` (najdou
všechny tři), `vrty pro tepelné čerpadlo` (skloňování), `kde je voda blízko pod
povrchem` (jen význam), `ČSN 75 9010` (jen slova), `sonda S-2` s filtrem
příloh (jen fulltext, přílohy nemají vektor).

API (`/api/health`, `/api/facets`, `POST /api/search`, `POST /api/compare`,
`POST /api/answer`, `POST /api/answer/stream`,
`/api/chunks/{doc}/{index}/context`, `/api/documents/{id}`,
`/api/documents/{id}/pdf`) má OpenAPI na
`http://localhost:8010/docs`. Nemá autentizaci a v Compose je jen na
`127.0.0.1` – posudky jsou interní.

Testy: `uv run pytest` v `data/scripts` (filtry, fúze, kontext, citace, API bez
databáze), `npm test` ve `frontend` (render nad hledáním i nad odpovědí
zachycenou z API, včetně otázky bez podkladů).

## Měření kvality vyhledávání

`data/eval/golden.yaml` obsahuje 40 českých otázek. U každé je dokument
a doslovný výňatek chunku, který na ni odpovídá. Otázky pokrývají skloňování,
přesné kódy a označení, parafráze, odpovědi ve více dokumentech a fakta jen
v přílohách. Šest otázek odpověď v korpusu nemá.

```powershell
uv run python eval_retrieval.py --check                    # ověří sadu proti databázi, zdarma
uv run python eval_retrieval.py                            # jeden embedding na otázku
uv run python eval_retrieval.py --modes fts --type annex   # bez volání API
```

Výstupem je recall@5, @10, @40 a MRR pro každý režim, rozpad podle typu
otázky, pořadí prvního relevantního chunku u každé otázky, přehled toho, co
vyhledávání vrací na otázky bez odpovědi, a s rerankingem i vyhodnocení brány
relevance. JSON se ukládá do `data/processed/eval/`. Režimy `fts_any`
a `hybrid_any` slouží jen k měření: jde o fulltext, který nevyžaduje všechna
slova dotazu.

Stav k 13. 9. 2026, spuštěno s `--modes fts fts_any vector hybrid hybrid_any rerank`:

| režim | recall@5 | recall@40 | MRR | odpověď není v top 40 |
| --- | ---: | ---: | ---: | ---: |
| fts | 0,04 | 0,09 | 0,06 | 31 z 34 |
| fts_any | 0,69 | 0,88 | 0,53 | 4 z 34 |
| vector | 0,62 | 0,83 | 0,53 | 5 z 34 |
| hybrid | 0,66 | 0,87 | 0,54 | 4 z 34 |
| hybrid_any | 0,69 | 0,90 | 0,54 | 3 z 34 |
| rerank | 0,92 | 0,96 | 0,79 | 1 z 34 |

Brána relevance se známkou 2 pustila relevantní úryvek u 33 z 34 otázek
s odpovědí a u všech 6 otázek bez odpovědi nepustila nic. Ohodnocení 40
kandidátů trvá v mediánu 6 s.

Relevance se určuje podle textu ([text_match.py](data/scripts/text_match.py)
ignoruje velikost písmen, zdvojené mezery a druh pomlčky), ne podle chunk_id,
takže sada přežije přechunkování. Po změně korpusu nebo sady nejdřív spusť
`--check`: výňatek, který nic nenajde, by se jinak tiše počítal jako nenalezený.

## Odpovědi s citacemi

Vyhledávání vrací pasáže. Nad ním stojí druhý režim, který z nalezených úryvků
složí odpověď a u každé věty uvede, ze kterého úryvku pochází.

```powershell
uv run python ask_reports.py "Kolik vrtů pro tepelné čerpadlo se v Roudně navrhuje?"
uv run python ask_reports.py "Jak hluboko je voda v Lednici?" --obec Lednice --max-sources 6
uv run python ask_reports.py "Jaká je vydatnost vrtu HV-979/3?" --show-prompt
```

Řetěz je: hybridní hledání s volnějším fulltextem, reranking, brána relevance,
výběr důkazů, jedno volání modelu a strojová kontrola odpovědi.

- **Bez podkladů se negeneruje.** Když žádný kandidát nedosáhne známky 2, model
  se vůbec nezavolá a odpověď má stav `no_evidence`. Uživatel dostane nejbližší
  nalezené úryvky, ať posoudí sám.
- **Do kontextu jde nejvýš osm úryvků**, z jednoho posudku v prvním kole nejvýš
  tři, se stropem deset tisíc tokenů. K úryvku, jehož sekce je rozdělená do víc
  oken, se přidá soused s rolí `kontext`.
- **Každá věta musí mít zdroj a doslovný citát.** Server pak citát hledá
  v citovaném úryvku a navíc ověřuje, že každé číslo z věty ve zdrojích opravdu
  je. Věta, která neprojde, se označí a stav klesne na `partial`. Čísla stran
  a kapitol do vět nepatří, ukazují se u citace.
- **Stavy odpovědi:** `answered`, `partial`, `insufficient` a `no_evidence`.
- **Model** nastavuje `GEMINI_ANSWER_MODEL`, výchozí je `GEMINI_MODEL`.
  Odpovídá se s teplotou 0 a prompt má vlastní verzi, která jde s každou
  odpovědí.
- **Stejná otázka se podruhé neplatí.** Odpověď se ukládá do
  `data/processed/answers/cache/`. Klíč drží otázku, filtry, nastavení, model,
  verzi promptu a otisk manifestu, takže po novém ingestu nebo změně promptu
  se odpovídá znovu. `--fresh` v CLI a „nová odpověď" na stránce vynutí nový
  výpočet, `--no-cache` cache úplně obejde.
- **Známky se platí jednou.** Ohodnocené kandidáty si drží proces v paměti
  a navíc `data/processed/answers/grades/`, takže druhý dotaz na stejnou otázku
  je nemá z čeho platit, i když běží v jiném procesu. Měřeno: 7,1 s
  známkování u nové otázky, 4 ms u otázky ohodnocené dřív. Klíč drží model,
  otázku i otisk korpusu, protože `chunk_id` přečkává i přechunkování.
- **Co se ptalo, se zapisuje.** Každá odpověď přidá řádek do
  `data/processed/answers/asked.jsonl`: otázka, věty s citáty a výsledkem
  kontroly, zdroje s dokumenty, počty z brány a kontextu a jestli šlo o nový
  výpočet, nebo o cache. Je to surovina pro další zlatou sadu, protože skutečné
  otázky jsou lepší než vymyšlené. Prompt a surová odpověď se do logu nepíšou.
  `--no-log` zápis vypne.

Přes API: `POST /api/answer` s tělem `{"question": "…", "filters": {…},
"options": {…}}`. Vrací věty s citacemi, zdroje s příznakem `cited`, chybějící
údaje, rozpory mezi zdroji a trace celého průběhu. Ve webovém rozhraní je to
záložka „Zeptat se dokumentů“, popsaná níž.

Kolik kandidátů se hodnotí, nastavuje `--candidates`. Měření ze 16. 9. 2026
ukazuje, že šetřit se na nich nevyplatí:

| kandidátů | recall@5 | recall@40 | MRR | brána pustila | otázky bez odpovědi uzavřela |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 40 | 0,924 | 0,956 | 0,806 | 33 z 34 | 6 z 6 |
| 24 | 0,894 | 0,926 | 0,792 | 32 z 34 | 6 z 6 |

Kvalitu odpovědí měří `eval_answers.py` nad stejnou zlatou sadou: jestli
odpověď citovala očekávaný úryvek, kolik vět prošlo kontrolou a jestli systém
mlčel tam, kde korpus odpověď nemá. Měření ze 15. 9. 2026 nad 40 otázkami:

| co se měřilo | výsledek |
| --- | ---: |
| odpovězeno / částečně / nedostatek podkladů | 28 / 4 / 2 |
| očekávaný úryvek byl v kontextu | 34 z 34 |
| odpověď ho i citovala | 31 z 34 |
| věty, které prošly kontrolou citací | 72 z 78 |
| otázky bez odpovědi v korpusu: systém mlčel | 6 z 6 |
| vymyšlená odpověď | 0 |
| medián času na otázku | 13,8 s |

Šest vět, které kontrolou neprošly, není chyba kontroly. Dvě měly citát, jehož
znění v citovaném úryvku není, jedna přidala k radonu číslo izotopu 222, jedna
změnila „podmínečně" na „podmíněně" a dvě přepisovaly tabulku z přílohy, kde
doslovný citát prakticky nejde pořídit. Kontrola čísel proto nepovažuje za
číslo to, co je nalepené na písmeno (vrt HV1, sonda J16), připouští mezeru mezi
číslicemi kvůli tabulkám a tisícům a bere jako oporu i hlavičku dokumentu.

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

Hotová a ověřená je celá cesta od PDF k odpovědi: zpracování posudků, hybridní
vyhledávání, reranking s bránou relevance, odpověď s ověřenými citacemi a webové
demo nad obojím. V databázi je **16 dokumentů a 2040 chunků**, z toho 1015
přílohových bez vektoru (dohledatelných fulltextem). Tři zdroje čekají na OCR
a do korpusu se nedostaly.

### Co bylo postaveno a co to vyřešilo

| co přibylo | co to řeší |
| --- | --- |
| **Zlatá sada a měření** — `data/eval/golden.yaml` (40 otázek), `eval_retrieval.py` | Do té doby se kvalita hledání odhadovala. První běh ukázal, že fulltext najde odpověď na otázku jen ve 3 případech z 34, protože `websearch_to_tsquery` spojuje všechna slova pomocí AND |
| **Volnější fulltext** — `fts_any`, řazený součtem IDF | Kandidáti pro reranking už nepotřebují všechna slova dotazu. Sám o sobě dosáhne recall@40 0,88 a je jediná cesta k faktům v přílohách, které nemají vektor |
| **Reranking a brána** — `rerank_service.py`, známka 0–3 od Gemini, práh 2 | Vektor vrátí výsledky na cokoli, i na nesmyslný dotaz, a skóre RRF se na práh nehodí. Známka je srozumitelné měřítko, na které se dá dát práh — a zavřená brána znamená, že se generování vůbec nespustí |
| **Výběr kandidátů po větvích** — 20 nejlepších z fulltextu a 20 z vektoru | Sloučené pořadí RRF systematicky nadržuje tomu, co našly obě větve, a vytlačovalo úryvky z příloh. Oprava přidala dvě správné odpovědi |
| **Sestavení kontextu** — `context_builder.py` | Nejvýš 8 úryvků, 3 z jednoho posudku, strop 10 tisíc tokenů, soused u rozdělené sekce. Méně kontextu je lepší; zdroje jdou modelu jako JSON s escapovanými `<` a `>`, otázka až za nimi |
| **Odpověď s pravidly** — `answer_prompts.py`, `answer_service.py`, `ask_reports.py`, `POST /api/answer` | Model odpovídá jen ze zdrojů, nepřevádí jednotky, nepřenáší zjištění mezi lokalitami a „nevím" je plnohodnotná odpověď (`insufficient`) |
| **Kontrola citací** — `citation_check.py` | Gemini nemá API pro citace vlastních dokumentů, takže záruku dodělává server: každý citát musí být v citovaném úryvku a každé číslo věty ve zdrojích. Co neprojde, sníží stav odpovědi |
| **Měření odpovědí** — `eval_answers.py` | Ukáže, jestli odpověď citovala očekávaný úryvek, kolik vět prošlo kontrolou a jestli systém mlčel tam, kde korpus odpověď nemá |
| **Webové rozhraní** — záložka „Zeptat se dokumentů", expert panel | Kolegům se dá ukázat nejen výsledek, ale i cesta k němu: kandidáti, známky, brána, kontext, prompt a surová odpověď modelu před kontrolou |
| **Kontrola vložených pokynů** — `injection_scan.py` v `check_pipeline.py` | Prompt injection se v promptu ošetřuje tím, že zdroje jsou data. Nikdo se ale nedozvěděl, že taková věta v korpusu je. Teď se to hlásí, a pravidla jsou úzká, aby „podle metodického pokynu MŽP" mlčelo |
| **Cache odpovědí a známek** — `answer_cache.py`, `grade_cache.py` | Demo se ptá pořád stejně a platilo pokaždé. Stejná otázka je teď za 0,55 s místo 22,9 s, dřív ohodnocení kandidáti za 4 ms místo 7,1 s. Klíč drží i otisk korpusu, takže po novém ingestu se počítá znovu |
| **Log otázek** — `answer_log.py` | Zlatou sadu psal člověk podle toho, co si myslel, že se kolegové zeptají. Skutečné otázky jsou lepší, a v logu jsou i s citáty a výsledkem kontroly, tedy přesně v podobě, jakou `golden.yaml` potřebuje |
| **Odkaz z citace do PDF** — `GET /api/documents/{id}/pdf` | Citace uváděla stranu, ale dojít na ni znamenalo hledat soubor ručně. Teď je to odkaz a prohlížeč otevře přímo tu stranu |
| **Průběh odpovědi** — `POST /api/answer/stream` | Deset až třicet sekund u jednoho spinneru vypadá jako zaseknutá stránka. Kroky se hlásí, jak nastávají, i s čísly |

Naměřené výsledky jsou v sekcích [Měření kvality vyhledávání](#měření-kvality-vyhledávání)
a [Odpovědi s citacemi](#odpovědi-s-citacemi). Ve zkratce: reranking zvedl
recall@5 z 0,66 na 0,92 a MRR z 0,54 na 0,79, brána propustila relevantní úryvek
u 33 z 34 zodpověditelných otázek a nepropustila nic u všech 6 nezodpověditelných,
z vygenerovaných odpovědí prošlo kontrolou 72 vět ze 78 a žádná z otázek bez
podkladu nedostala vymyšlenou odpověď.

### Otevřené věci

| věc | stav | proč se to nechalo |
| --- | --- | --- |
| **Tři skeny bez OCR** | mimo korpus | OCR je krok mimo pipeline; na stroji není `ocrmypdf` ani `tesseract`. Běh je ohlásí jako `skipped` a pokračuje dál |
| **Svazky více zpráv v jednom PDF** | Sedmirohé (11 zpráv) a Metan jih (5) mají běh chunků pod `8. Závěr > 3.2. Podzemní vody` | správné řešení je rozpad na samostatné dokumenty, což se dotýká identity dokumentu, extrakce i citací |
| **Prozaická příloha bez formulářových stran** | ZZ_Pazderna: 34 chunků pod `6.1 SEZNAM NOREM` | hranice přílohy se hledá jako formulářová strana; když žádná za posledním nadpisem není, nemá na co ukázat |
| **Jeden chunk bez sekce** | Monitoring, chunk #0 (rozdělovník a seznam příloh) | důsledek pravidla „žádný titulek je lepší než špatný"; `check_pipeline` to hlásí jako CHYBU, i když jde o front matter |
| **Extrakční schéma je provizorní** | `report_type` je volný text, `extra_fields` sbírá zbytek | vzniklo dřív než reálné posudky. Teď je poprvé dost dat: `cislo_zakazky`, `cislo_geofond`, `hydrogeologicky_rajon`, `hloubka_vrtu`, `vystroj_vrtu` se opakují napříč dokumenty. Postup je v `.claude/skills/data-ingestion/SKILL.md` |
| **Reranking je nejpomalejší krok** | u nové otázky 7 až 13 s, u dřív ohodnocené 4 ms | změřeno: menší dávky nepomáhají (latence je na volání, ne na kandidáta) a méně kandidátů měřitelně zhoršuje výsledky. Zbývá tedy neznámkovat znovu, což řeší cache známek na disku |
| **Režim Fulltext zůstává přísný** | na otázky v přirozeném jazyce najde odpověď jen u 3 z 34 | záměr: ve Vyhledávání ukazuje limity hledání podle slov. Kandidáti pro reranking používají volnější fulltext, který nevyžaduje všechna slova |
| **Doslovný citát z tabulky v příloze** | občas neprojde kontrolou | model řádek tabulky přeformátuje, takže citát nesedí znak po znaku a věta zůstane označená jako neověřená, i když čísla souhlasí. Týká se 2 vět ze 78 |
| **Citace ze svazku ukáže cizí sekci** | čeká na rozpad svazků | u Sedmirohé a Metan jih sedí chunky pod nadpisem z jiné dílčí zprávy, takže i správně nalezený úryvek se cituje se špatnou sekcí |

### Další postup

Z osmi bodů, které tady stály, je šest hotových: kontrola vložených pokynů, log
otázek, cache odpovědí, odkaz do PDF, průběh odpovědi a reranking. U rerankingu
je závěr negativní a stojí za zapamatování — menší dávky nepomáhají, protože
latence je na volání, ne na kandidáta, a méně kandidátů měřitelně zhoršuje
výsledky (tabulka v [Měření kvality vyhledávání](#měření-kvality-vyhledávání)).
Ušetřit šlo jen tím, že se stejná práce nedělá dvakrát.

Zbývají dvě věci a obě stojí placený přeběh celého korpusu, takže patří
k rozhodnutí, ne k běžné práci:

1. **Rozpad svazků na dílčí zprávy.** Největší otevřená strukturální věc.
   `GF_P188240_ZZ Sedmirohé 10 sond` je jedenáct zpráv pod jedním přebalem
   a `Metan jih` pět; jejich chunky sedí pod nadpisem z cizí dílčí zprávy,
   takže i správně nalezený úryvek se cituje se špatnou sekcí. Dotýká se
   identity dokumentu (jeden soubor, víc řádků v `documents`), extrakce (jedno
   volání na dílčí zprávu) i citací, chce vlastní návrh a nové nahrání obou
   svazků.
2. **Doladění extrakčního schématu.** `cislo_zakazky`, `cislo_geofond`,
   `hydrogeologicky_rajon`, `hloubka_vrtu` a `vystroj_vrtu` se opakují napříč
   posudky, takže je poprvé dost dat povýšit je na sloupce a zúžit
   `report_type` na `Literal`. Zvednutí `SCHEMA_VERSION` ale znamená znovu
   extrahovat i zaembeddovat všech 16 posudků, což se platí. Postup je
   v `.claude/skills/data-ingestion/SKILL.md`.

### Na co si dát pozor

**Verze jsou slib.** `MARKDOWN_VERSION`, `SCHEMA_VERSION` a `CHUNKER_VERSION`
znamenají „stejná verze = stejný výstup". Když změníš logiku normalizéru nebo
chunkeru a verzi nezvedneš, manifest nechá v databázi staré chunky a označí je za
aktuální — tichá nekonzistence, kterou nic nenahlásí. Stalo se to při vývoji
`content_kind`: dva dokumenty si nechaly chunky ze staré logiky.

**Návratový kód nestačí.** Průchod skončí s kódem 0 i tehdy, když část výsledku
neodpovídá kódu, který ho vyrobil. Ověřuj přepočtem: načti Markdown, spočítej
chunky znovu a porovnej s parquetem a s databází.

**Ověřuj po každé dávce, ne až na konci.** Embeddingy se platí. Dvě opravy
(dohledání stránek, `content_kind`) vyšly najevo až při kontrole a znamenaly
přepočet — kdyby dávky běžely za sebou bez ověření, platily by se vícekrát.

**Diakritika se přes shell nepřenese.** Seznam dokumentů předaný jako argument
se rozbije na `Orli?ky`. Volej `ingest.main([...])` z Pythonu se jmény načtenými
z manifestu.

**Migrace nesmí mazat.** SQL v `data/scripts/sql/` musí být opakovaně
spustitelné: `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, nikdy
`DROP`. Databáze obsahuje reálné dokumenty.

**Obraz PostgreSQL není standardní.** Staví se z `postgres/Dockerfile` a nese
český hunspell slovník. Bez `docker compose build postgres` se české skloňování
tiše rozbije (`text search configuration "czech" does not exist`).

**Port 5432 je publikovaný**, takže naráz může běžet jen jeden projekt
s PostgreSQL. `name: vectorsearch` v compose souboru neodstraňuj — bez něj si
Compose odvodí jméno z adresáře a recykluje kontejnery cizího projektu.

**Bind mount `deploy/local/data/postgres` drží data.** Nikdy ho nemaž
a nepouštěj `docker compose down -v` ani `--remove-orphans` bez rozmyslu.

## Bezpečnost

- Posudky jsou interní dokumenty organizace. `data/PDFs/` je gitignorovaný.
- Přihlašovací údaje patří do `.env`, verzují se jen `.env.template`.
- Extrakce je striktně groundovaná na text dokumentu — model nesmí nic domýšlet.
