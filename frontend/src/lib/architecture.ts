// The pipeline explained to a person, not to a machine.
//
// Everything the architecture tab shows lives here as data: the diagram and the
// detail panel render from the same array, so a step can never appear in one and
// be missing from the other. The numbers are written down with the date they were
// measured rather than fetched from the API, because a page that explains the
// system has to work when the system is down.
//
// Sources, in order of authority: README.md, CLAUDE.md, data/scripts/README.md
// ("Notes"), the comments in data/scripts/sql/ and .claude/skills/.

/** What a step costs to run: nothing, a database query, or a paid model call. */
export type Cost = 'local' | 'sql' | 'paid'

export type PhaseId = 'prep' | 'store' | 'retrieve' | 'answer'

/** Which half of the fork a step belongs to, when it is one of the two branches. */
export type BranchSide = 'fts' | 'vector'

/** A free-standing block in the detail panel: prose, a table, SQL or an aside. */
export interface Block {
  kind: 'text' | 'table' | 'code' | 'note'
  title?: string
  text?: string[]
  table?: { head: string[]; rows: string[][] }
  code?: string
}

/** Everything the detail panel can render. Steps and cross-cutting topics share it. */
export interface Detail {
  id: string
  title: string
  lead: string
  tech: string[]
  what: string[]
  gotchas?: { title: string; text: string }[]
  safeguard?: string[]
  numbers?: { label: string; value: string }[]
  blocks?: Block[]
  files: string[]
}

export interface Step extends Detail {
  phase: PhaseId
  cost: Cost
  /** What the step leaves behind on disk or in the database. */
  artifact?: string
  branch?: BranchSide
}

export interface Topic extends Detail {
  /** One-word tag on the card. */
  tag: string
}

export interface Phase {
  id: PhaseId
  number: string
  title: string
  lead: string
}

export const COST_INFO: Record<Cost, { label: string; badge: string; swatch: string }> = {
  local: {
    label: 'zdarma, běží lokálně',
    badge: 'bg-slate-100 text-slate-600',
    swatch: 'bg-slate-300',
  },
  sql: {
    label: 'dotaz do PostgreSQL',
    badge: 'bg-blue-100 text-blue-700',
    swatch: 'bg-blue-500',
  },
  paid: {
    label: 'placené volání Gemini',
    badge: 'bg-violet-100 text-violet-700',
    swatch: 'bg-violet-500',
  },
}

export const PHASES: Phase[] = [
  {
    id: 'prep',
    number: '1',
    title: 'Zpracování posudku',
    lead: 'Běží jednou na dokument, mimo provoz. Z PDF vznikne struktura, metadata a chunky s vektory.',
  },
  {
    id: 'store',
    number: '2',
    title: 'Uložení a index',
    lead: 'Dvě tabulky, tři druhy indexu a český slovník. Vyhledávání není samostatný stroj, je to SQL.',
  },
  {
    id: 'retrieve',
    number: '3',
    title: 'Od dotazu k pasážím',
    lead: 'Dvě větve hledají nezávisle, sloučí se do kandidátů, model je oznámkuje a brána rozhodne.',
  },
  {
    id: 'answer',
    number: '4',
    title: 'Od pasáží k odpovědi',
    lead: 'Nejvýš osm úryvků, jedno volání modelu a strojová kontrola každé věty proti citovanému úryvku.',
  },
]

/** The pipeline, in the order a document and then a question travels through it. */
export const STEPS: Step[] = [
  {
    id: 'pdf',
    phase: 'prep',
    title: 'Zdrojové PDF',
    lead: 'Geologický posudek tak, jak přišel. Do gitu se neukládá, je interní.',
    cost: 'local',
    artifact: 'data/PDFs/<název>.pdf',
    tech: ['data/PDFs', '.gitignore'],
    what: [
      'PDF se zkopíruje do data/PDFs a tím vstupuje do pipeline. Samo o sobě se do PostgreSQL neukládá.',
      '18 souborů na disku dnes, z toho 16 dokumentů má i výstup v databázi — zbylé tři jsou skeny bez textové vrstvy.',
      'ingest.py je inkrementální: nový soubor pozná podle sha256 a projede jím všechny čtyři fáze, beze změny se nic nepočítá znovu.',
    ],
    gotchas: [
      {
        title: 'Sken bez OCR vrstvy',
        text: 'Když stránka nemá žádný stripnutý text, extrakce to pozná a dokument označí jako "skipped" — pipeline pokračuje dál, dokument prostě zůstane mimo korpus. Tři dnes čekají na OCR, které pipeline neumí.',
      },
      {
        title: 'Diakritika a shell',
        text: 'Seznam dokumentů předaný přes příkazovou řádku se rozbije na "Orli?ky". Skripty se proto volají z Pythonu se jmény načtenými z manifestu, ne z shellu.',
      },
    ],
    numbers: [
      { label: 'PDF na disku', value: '18' },
      { label: 'v databázi', value: '16' },
      { label: 'čeká na OCR', value: '3' },
    ],
    files: ['data/scripts/ingest.py', 'data/scripts/pipeline_common.py'],
  },
  {
    id: 'text',
    phase: 'prep',
    title: 'Čtení PDF',
    lead: 'Jeden průchod pdfminerem po stranách. Z téhož průchodu je text i mapa stran.',
    cost: 'local',
    artifact: '<stem>.pages.json',
    tech: ['pdfminer.six', 'LAParams'],
    what: [
      'pdf_pages() otevře soubor jednou a projde ho stránku po stránce nízkoúrovňovým API pdfmineru (PDFResourceManager, TextConverter, PDFPageInterpreter).',
      'Ze stejného průchodu vzniknou dva výstupy: text pro Markdown a <stem>.pages.json — prostý JSON seznam řetězců, jeden na stranu.',
      'Pozdější krok locate_pages() hledá text chunku v tomto seznamu stran. Musí jít o stejný extraktor, který text vyrobil, jinak se citace stránek rozjede.',
    ],
    gotchas: [
      {
        title: 'Proč ne dvě knihovny',
        text: 'Dřívější nastavení používalo jeden nástroj na Markdown a jiný na mapu stran. Stránku se podařilo dohledat jen u 63 % chunků. Jeden engine to zvedl na 98 %.',
      },
      {
        title: 'Chybějící textová vrstva',
        text: 'Když žádná strana nemá stripnutý text, vyhodí se MissingTextLayer a dokument se počítá jako "skipped", ne jako chyba — pipeline nespadne, jen dokument nechá bez zpracování.',
      },
    ],
    numbers: [
      { label: 'dohledání strany', value: '63 % → 98 %' },
      { label: 'per-page extract_text', value: '~2× pomalejší' },
    ],
    files: ['data/scripts/extract_reports.py'],
  },
  {
    id: 'pagekind',
    phase: 'prep',
    title: 'Klasifikace stran',
    lead: 'Každá strana je próza, formulář, nebo prázdná — podle dvou čísel, obou najednou.',
    cost: 'local',
    artifact: '<stem>.pagekind.json',
    tech: ['dlouhé řádky < 12 %', 'funkční slova < 6 %'],
    what: [
      'Pro každou stranu se spočítá podíl dlouhých řádků (≥ 45 znaků, tedy souvislá věta zalomená až na okraji) a podíl funkčních slov (je, se, byl, nebo…).',
      'Formulář je jen strana, kde jsou nízko obě čísla najednou — to je celá pointa konjunkce. Samotná nízká slovesnost by zahodila vrtné protokoly, které mají funkčních slov jen asi 1 %, ale drží je dlouhé litologické popisy.',
      'Do seznamu funkčních slov nepatří předložky. Samotné "od - do:" drželo 93 vrtných protokolů nad prahem, dokud předložky nevypadly ze seznamu.',
      'Doplňková pravidla: běh kratší než 2 strany se pohltí okolím, prázdné strany běh nepřerušují, a úvodní běh až 3 stran je obálka, ne příloha.',
    ],
    gotchas: [
      {
        title: 'Prahy jsou naladěné na 15 posudků',
        text: '12 % / 6 % dělí tento korpus čistě (zdravé dokumenty 0–8,8 %, problémové 28,5–79,5 %), ne korpus obecně. Posudek od jiného zpracovatele může vyjít jinak — check_pipeline --triage to ukáže ve sloupci "přílohy".',
      },
      {
        title: 'Titulní strana vypadá jako formulář',
        text: 'Krátké řádky, žádná slovesa — bez pravidla o obálce by titulní strana spadla do přílohy a odnesla s sebou dobrý titulek. Delší obálka než 3 strany toto pravidlo obejde.',
      },
    ],
    numbers: [
      { label: 'dlouhé řádky', value: '< 12 %' },
      { label: 'funkční slova', value: '< 6 %' },
      { label: 'obálka nejvýš', value: '3 strany' },
    ],
    files: ['data/scripts/page_classifier.py'],
  },
  {
    id: 'normalize',
    phase: 'prep',
    title: 'Normalizace Markdownu',
    lead: 'Sedm pravidel v pevném pořadí složí zpátky nadpisy, které extraktor nezná.',
    cost: 'local',
    artifact: '<stem>.md + <stem>.removed.json',
    tech: ['MARKDOWN_VERSION = 6', 'difflib'],
    what: [
      'PDF extraktor vrací holý text bez písem a stylů — nadpis od odstavce nepozná. Bez rekonstrukce by celý posudek byl jeden blok bez citace.',
      '1. Odsazení přílohy — formulářové strany a vše za hranicí přílohy se odloží a připojí pod "## Přílohy" dřív, než začne cokoli jiného měřit.',
      '2. Rozbalení layoutových tabulek — blok "|"-řádků s méně než 60 % vyplněných buněk je sloupcový layout, ne data.',
      '3. Mazání záhlaví a patiček — řádek do 160 znaků opakovaný na polovině stran (min. 3×) je paginace. Signatura musí obsahovat slovo o 3 písmenech, jinak by mazala laboratorní hodnoty jako "<0," nebo "207."',
      '4. Vytažení obsahu — položka je "číslo … tečky … strana" (≥ 4 tečky), potřeba jsou aspoň 3. Bloky dál než 40 řádků od sebe se mažou zvlášť.',
      '5. Povýšení nadpisů podle obsahu — "1." → "##", "1.1" → "###", hloubka max 4. Párování je fuzzy (85 % podobnost), protože extraktor umí vynechat glyfy.',
      '6. Titulek dokumentu — odmítne se osoba, firma, adresa, kontakt, položka seznamu. Když žádný vhodný řádek není, nepovýší se nic — špatný titulek je horší než žádný.',
      '7. Pojistka ztráty — když by mazání zahodilo víc než 25 % písmen a číslic, zopakuje se bez mazání záhlaví; teprve pak se vrátí surový text.',
    ],
    gotchas: [
      {
        title: 'Sentence opening with a number',
        text: 'Věta začínající číslem vypadá jako nadpis ("4 EO (ekvivalentní obyvatele) z každé projektované stavby RD"). Nadpis se proto počítá jen tehdy, je-li jeho číslo uvedené v obsahu.',
      },
      {
        title: 'Pojistka je pořád vše-nebo-nic',
        text: 'Při překročení 25 % se zahodí celá normalizace včetně správně nalezených nadpisů — odstupňováno je to jen na jednu úroveň (bez mazání záhlaví), druhá úroveň zůstává skoková.',
      },
    ],
    numbers: [
      { label: 'MARKDOWN_VERSION', value: '6' },
      { label: 'podobnost titulků', value: '85 %' },
      { label: 'strop ztráty', value: '25 %' },
    ],
    files: ['data/scripts/markdown_normalizer.py'],
  },
  {
    id: 'annex',
    phase: 'prep',
    title: 'Hranice přílohy',
    lead: 'Vrtné protokoly za poslední kapitolou se odloží pod `## Přílohy`, ať nedědí cizí nadpis.',
    cost: 'local',
    artifact: '## Přílohy',
    tech: ['_annex_start()'],
    what: [
      'Formulářové strany nejsou celá příloha. Vrtné protokoly jsou próza podle všech měřítek, ale leží za poslední kapitolou — bez hranice by zdědily její nadpis.',
      'Pravidlo: hranice je první formulářová strana za poslední stranou, která nese číslovaný nadpis uvedený v obsahu.',
      'Požadavek "uvedený v obsahu" je nutný — bez něj se za nadpis počítá věta začínající číslem a hranice by přeskočila přílohu celou.',
      'Pravidlo drží i pro svazek víc zpráv v jednom PDF: dílčí zprávy číslují až do konce, takže hranice padne pozdě místo aby spolkla jejich strukturu.',
    ],
    gotchas: [
      {
        title: 'Neopravená chyba, kterou tohle řeší',
        text: '130 z 216 chunků jednoho posudku bylo bez hranice citováno jako "8.4. Závěrečné zhodnocení", protože vrtné protokoly za touto kapitolou zdědily její nadpis.',
      },
    ],
    files: ['data/scripts/markdown_normalizer.py'],
  },
  {
    id: 'extract',
    phase: 'prep',
    title: 'Strukturovaná extrakce',
    lead: 'Gemini vyplní Pydantic schéma. Co v dokumentu není, se nedomýšlí — přizná se.',
    cost: 'paid',
    artifact: 'extracted/<stem>.json → documents',
    tech: ['Gemini', 'response_schema', 'SCHEMA_VERSION = 1'],
    what: [
      'Celý normalizovaný Markdown jde jako jeden vstup do Gemini s Pydantic modelem GeologicalReport jako response_schema, teplota 0.',
      'Schéma je provizorní schválně — report_type je volný text, ne Literal, protože byl napsaný dřív, než existoval jediný reálný posudek.',
      'Každé pole je povinné (žádné Pydantic defaults) — model musí vrátit null nebo prázdný seznam, ne pole vynechat. missing_fields navíc nutí model přiznat, co nenašel.',
      'extra_fields sbírá vše důležité, co schéma nepokrývá — je to mechanismus, kterým se schéma bude časem dolaďovat.',
    ],
    safeguard: [
      'EXTRAKCE MUSÍ BÝT STRIKTNĚ ZALOŽENÁ NA TEXTU DOKUMENTU. Žádné odvozování, žádné dopočítávání, žádné doplňování z obecných znalostí — u geologického posudku by vymyšlená hladina podzemní vody byla bezpečnostní chyba, ne kosmetická.',
    ],
    numbers: [
      { label: 'SCHEMA_VERSION', value: '1' },
      { label: 'teplota', value: '0.0' },
      { label: 'polí ve schématu', value: '14' },
    ],
    files: ['data/scripts/extract_reports.py', 'data/scripts/schemas.py'],
  },
  {
    id: 'chunk',
    phase: 'prep',
    title: 'Chunking podle sekcí',
    lead: 'Cesta nadpisů se stane citací. Velká sekce se rozdělí do oken s překryvem.',
    cost: 'local',
    tech: ['800 / 100 / 150 tokenů', 'tiktoken', 'CHUNKER_VERSION = 4'],
    what: [
      'Čistá funkce — žádné API, žádná databáze, testovatelná bez přihlašovacích údajů.',
      'Dělení podle nadpisů: cesta nadpisů (Kapitola > Podkapitola) se stane sekcí a je citační jednotkou.',
      'Nad CHUNK_MAX_TOKENS (800) se sekce dělí na hranicích odstavců, s překryvem CHUNK_OVERLAP_TOKENS (100). Když se celé odstavce na překryv nevejdou, uřízne se konec posledního.',
      'Nadpis jde do každého okna, ne jen prvního — jinak by se dlouhá sekce nedala najít podle názvu, protože fts_chunk se staví z chunk_raw.',
      'Slučování malých sekcí platí jen uvnitř stejné sekce — přes hranici nadpisu by malá sekce zdědila cizí popisek.',
      'Limit se vynucuje po spojení, ne po odstavcích — separátory se dřív nepočítaly a chunky limit přerůstaly.',
    ],
    gotchas: [
      {
        title: 'tiktoken počítá češtinu níž než Gemini',
        text: 'Jiný tokenizér, rozdíl 10–30 %. Cíl 800 proti limitu 2048 tokenů Gemini to pokrývá s rezervou, ale při zvyšování CHUNK_MAX_TOKENS je třeba na to pamatovat.',
      },
      {
        title: 'Malé sekce zůstávají malé',
        text: 'Chunky o 32 tokenech existují záměrně — správný popisek je cennější než velikost. check_pipeline to hlásí, ale neopravuje.',
      },
    ],
    numbers: [
      { label: 'CHUNK_MAX_TOKENS', value: '800' },
      { label: 'CHUNK_OVERLAP_TOKENS', value: '100' },
      { label: 'CHUNK_MIN_TOKENS', value: '150' },
      { label: 'CHUNKER_VERSION', value: '4' },
    ],
    files: ['data/scripts/chunker.py'],
  },
  {
    id: 'embed',
    phase: 'prep',
    title: 'content_kind a embeddingy',
    lead: 'Próza dostane vektor, vyplněný formulář ne. Popisek a cena jsou dvě různé otázky.',
    cost: 'paid',
    artifact: 'chunks/<stem>.parquet',
    tech: ['gemini-embedding-001', '1536 dimenzí', 'RETRIEVAL_DOCUMENT'],
    what: [
      'Dvě nezávislé otázky, dva nezávislé zdroje: jak se chunk cituje rozhoduje pozice v dokumentu (normalizér vloží "## Přílohy"); jestli se platí za embedding rozhoduje typ stránky (content_kind z pagekind.json).',
      'Proto mají vrtné popisy citaci "… > Přílohy" (pravdivou) a zároveň vektor (protože jsou to prózou). Kdyby obojí viselo na jednom signálu, jedno by se ztratilo.',
      'Chunk, jehož stránku se nepodařilo dohledat (~4 %), se počítá jako próza — nedohledaná strana stojí embedding navíc, ale nevyrobí díru v indexu.',
      'gemini-embedding-001 s task_type=RETRIEVAL_DOCUMENT, output_dimensionality=1536. Truncated vektor se L2-normalizuje (normalize() v gemini_auth.py) — Gemini dokumentuje, že po zkrácení pod 3072 dimenzí (Matryoshka) je renormalizace potřeba.',
      'Kontextový prefix "KONTEXT: …" (titul, lokalita, typ, shrnutí) se přidá před embeddingem, ale nestojí žádné další volání — je to vedlejší produkt extrakce.',
    ],
    gotchas: [
      {
        title: 'Proč 1536, ne 3072',
        text: 'Gemini nabízí 128–3072 dimenzí (doporučené úrovně 768/1536/3072), ale HNSW index pgvectoru přijímá nejvýš 2000. 1536 je největší doporučená úroveň, která se vejde.',
      },
      {
        title: 'Prefix se nezapočítává do token_count',
        text: 'KONTEXT: přidává ~250 tokenů, ale token_count měří text bez něj. Skutečný vstup do modelu je větší, než sloupec říká — varování se vypíše nad 1500 tokenů.',
      },
    ],
    numbers: [
      { label: 'dimenze', value: '1536' },
      { label: 'nezaembeddováno', value: '1015 / 2040 chunků' },
    ],
    files: ['data/scripts/chunk_and_embed.py', 'data/scripts/gemini_auth.py'],
  },
  {
    id: 'import',
    phase: 'prep',
    title: 'Import do PostgreSQL',
    lead: 'Dokument se upsertuje, chunky se nahradí celé. Nikdy se nemaže tabulka.',
    cost: 'sql',
    artifact: 'documents + document_chunks',
    tech: ['psycopg2', 'ON CONFLICT (source_file)'],
    what: [
      'documents: upsert na ON CONFLICT (source_file) — dokument se aktualizuje, ne duplikuje.',
      'document_chunks: DELETE podle document_id, pak INSERT všech nových — chunky se nahrazují celé, protože se jejich počet mění s parametry chunkeru a upsert po chunk_index by nechal osiřelé řádky.',
      'Přílohové chunky mají embedding = NULL (to_pgvector vrátí None) — zůstávají v chunk_raw a tedy ve fts_chunk, jen je nenajde vektorová větev.',
      'Jedna transakce na dokument: commit po každém, rollback na chybě — jeden vadný dokument nezastaví dávku.',
    ],
    numbers: [{ label: 'v databázi', value: '16 dokumentů, 2040 chunků' }],
    files: ['data/scripts/import_reports.py'],
  },
  {
    id: 'manifest',
    phase: 'prep',
    title: 'Manifest a verze',
    lead: 'Co se udělalo a za jakých parametrů. Stejná verze je slib, že je stejný i výstup.',
    cost: 'local',
    artifact: 'data/processed/manifest.json',
    tech: ['sha256', 'chunk_params_hash'],
    what: [
      'Jeden záznam na dokument: sha256 zdroje, verze každé fáze (MARKDOWN_VERSION, SCHEMA_VERSION, chunk_params_hash, embedding model a dimenze) a časová značka každé fáze.',
      'Invalidace je kaskádová: změna sha256 nebo verze rané fáze zneplatní ji i všechno po ní — markdown → extract → chunk → import.',
      'Pipeline je inkrementální, ne dávková: ingest.py přepočítá jen to, co manifest označí za neplatné, nikdy vše znovu.',
    ],
    safeguard: [
      'Verze jsou slib: "stejná verze = stejný výstup". Změníš-li logiku normalizéru nebo chunkeru a verzi nezvedneš, manifest nechá v databázi staré chunky a označí je za aktuální — tichá nekonzistence, kterou nic nenahlásí. Stalo se to při vývoji content_kind: dva dokumenty si nechaly chunky ze staré logiky.',
    ],
    gotchas: [
      {
        title: 'Návratový kód nestačí',
        text: 'Průchod skončí s kódem 0 i tehdy, když část výsledku neodpovídá kódu, který ho vyrobil. Ověřuje se přepočtem: načíst Markdown, spočítat chunky znovu, porovnat s parquetem a databází.',
      },
    ],
    files: ['data/scripts/manifest.py', 'data/scripts/ingest.py'],
  },
  {
    id: 'check',
    phase: 'prep',
    title: 'Kontrola výsledku',
    lead: 'Nic nezapisuje, nic nestojí. Hledá tiché chyby — a věty, které mluví k modelu.',
    cost: 'local',
    tech: ['check_pipeline.py', 'injection_scan.py'],
    what: [
      'check_pipeline.py nic nezapisuje, nevolá API, nestojí nic. Návratový kód 1 při chybě.',
      'U každého dokumentu ověří: počet nadpisů, zbytky po konverzi, mapu stránek, extrakci a schéma, počet a velikost chunků, že každý chunk má sekci, podíl chunků s číslem stránky, dimenze embeddingů, shodu s databází, naplněný fulltextový index a zkusí slova ze středu dokumentu opravdu vyhledat.',
      '--triage vypíše jen to, co potřebuje rozhodnutí, seskupené podle akce. --removed ukáže, co normalizátor smazal a podle jakého pravidla.',
      'injection_scan.py hledá v chunkách věty, které mluví k modelu, ne ke čtenáři — "ignoruj předchozí pokyny", přidělení role, diktovanou odpověď, napodobený systémový prompt, česky i anglicky.',
    ],
    safeguard: [
      'Do promptu jdou zdroje jako data, takže scan není obrana — je to jediné místo, kde se člověk dozví, že taková věta v korpusu je. Pravidla jsou úzká schválně: běžné "podle metodického pokynu MŽP" mlčí, protože se hlásí až sloveso rušící dřívější zadání.',
    ],
    numbers: [{ label: 'čistých dokumentů', value: '16 / 16' }],
    files: ['data/scripts/check_pipeline.py', 'data/scripts/injection_scan.py'],
  },

  {
    id: 'model',
    phase: 'store',
    title: 'Datový model',
    lead: 'Dvě tabulky: jeden řádek na posudek, jeden řádek na chunk.',
    cost: 'sql',
    artifact: 'documents · document_chunks',
    tech: ['PostgreSQL 17', 'JSONB', 'vector(1536)'],
    what: [
      'documents: typované jádro (title, locality, report_date, author, client, summary) je stabilní napříč jakýmkoli budoucím schématem; doménově specifická pole žijí v extraction_json JSONB, dokud se schéma nedoladí podle reálných posudků.',
      'document_chunks: chunk_raw je doslovný text, cituje se a indexuje pro fulltext; chunk_text je to, co se skutečně embeddovalo (může nést kontextový prefix). Citační jednotkou je section — cesta Markdown nadpisů.',
      'content_kind je prose nebo annex; přílohové chunky mají embedding IS NULL a jsou dohledatelné jen fulltextem.',
      'page_from/page_to jsou best-effort a mohou být NULL, když se stránku nepodařilo dohledat.',
    ],
    blocks: [
      {
        kind: 'table',
        title: 'document_chunks — hlavní sloupce',
        table: {
          head: ['sloupec', 'typ', 'poznámka'],
          rows: [
            ['chunk_id', 'UUID UNIQUE', 'uuid5(document_id:chunk_index), přežije přechunkování'],
            ['section', 'TEXT', 'cesta Markdown nadpisů, citační jednotka'],
            ['chunk_raw', 'TEXT NOT NULL', 'doslovný text — cituje se a indexuje'],
            ['chunk_text', 'TEXT NOT NULL', 'to, co šlo do embeddingu (může nést KONTEXT: prefix)'],
            ['embedding', 'vector(1536)', 'NULL u přílohových chunků'],
            ['content_kind', "TEXT DEFAULT 'prose'", "'prose' nebo 'annex'"],
          ],
        },
      },
    ],
    files: ['data/scripts/sql/tables/01_create_documents.sql', 'data/scripts/sql/tables/02_create_document_chunks.sql'],
  },
  {
    id: 'index',
    phase: 'store',
    title: 'Indexy a trigger',
    lead: 'HNSW na význam, GIN na slova. Tsvector plní trigger, ne generovaný sloupec.',
    cost: 'sql',
    tech: ['pgvector HNSW', 'GIN', 'BEFORE INSERT OR UPDATE'],
    what: [
      'HNSW index nad embedding: vector_cosine_ops, m = 16, ef_construction = 64. hnsw.ef_search se nastavuje za běhu na počet řádků, které se mají natáhnout (transakčně lokální).',
      'GIN index nad fts_chunk pro fulltext, plus btree na document_id a (document_id, content_kind).',
      'fts_chunk NENÍ generovaný sloupec — plní ho trigger BEFORE INSERT OR UPDATE OF chunk_raw, protože funkce unaccent() je STABLE, ne IMMUTABLE, a GENERATED to vyžaduje.',
    ],
    blocks: [
      {
        kind: 'code',
        title: 'HNSW index (data/scripts/sql/tables/02_create_document_chunks.sql)',
        code: `CREATE INDEX IF NOT EXISTS idx_chunks_embedding_cosine
    ON public.document_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_chunks_fts
    ON public.document_chunks USING GIN (fts_chunk);`,
      },
    ],
    numbers: [
      { label: 'm', value: '16' },
      { label: 'ef_construction', value: '64' },
    ],
    files: ['data/scripts/sql/tables/02_create_document_chunks.sql', 'data/scripts/sql/tables/04_add_content_kind.sql'],
  },
  {
    id: 'czech',
    phase: 'store',
    title: 'Český fulltext',
    lead: 'PostgreSQL nemá český stemmer. Doplní ho hunspell — a indexují se dvě konfigurace naráz.',
    cost: 'sql',
    tech: ['hunspell-cs', 'czech', 'czech_literal'],
    what: [
      'PostgreSQL má Snowball stemmery pro 28 jazyků, čeština mezi nimi není. Bez zásahu jediná možnost byla konfigurace "simple", která jen malými písmeny — sekce "Technické parametry vrtů" se nenašla dotazem "vrty".',
      'postgres/Dockerfile doinstaluje hunspell-cs (slovník LibreOffice) a přejmenuje jeho .aff/.dic na czech.affix/czech.dict — ispell šablona PostgreSQL je čte obráceně, odvozuje kmen z tvaru.',
      'Vznikají dvě konfigurace: czech (morfologie + stopslova, vrtů i vrty → vrt) a czech_literal (dřívější chování: odstranit diakritiku, indexovat doslovně).',
      'Chunky se indexují oběma najednou — trigger sestaví fts_chunk jako to_tsvector(czech, …) || to_tsvector(czech_literal, …) — a dotaz se ptá obou přes OR.',
      'Mapuje se všech šest typů tokenů (asciiword, asciihword, hword_asciipart, word, hword, hword_part), ne jen "word" — jinak by "vrty" šlo do simple slovníku a "vrtu" do českého a nikdy by se nepotkaly.',
    ],
    gotchas: [
      {
        title: 'Proč ne jen jedna konfigurace',
        text: 'Morfologie sama by nenašla dotaz psaný bez diakritiky. Odháčkovat samotný slovník nejde — kolabuje to 12 000 z jeho 261 000 hesel a mění 517 přiřazovacích pravidel, měřitelně rozbíjí fungující tvary ("hladiny" přestane vést na "hladina").',
      },
      {
        title: 'Degradace, ne pád',
        text: 'Chybí-li czech.affix/czech.dict/czech.stop, 03_create_czech_fts.sql selže a zůstane trigger "simple" z kroku 02 — dřívější fungující chování, schválně místo pádu.',
      },
    ],
    blocks: [
      {
        kind: 'code',
        title: 'Trigger (data/scripts/sql/tables/03_create_czech_fts.sql)',
        code: `NEW.fts_chunk :=
    to_tsvector('public.czech', coalesce(NEW.chunk_raw, ''))
    || to_tsvector('public.czech_literal', coalesce(NEW.chunk_raw, ''));`,
      },
      {
        kind: 'text',
        title: 'Pořadí SQL souborů',
        text: [
          'extensions/01_install_pgvector.sql → extensions/02_install_unaccent.sql → tables/01_create_documents.sql → tables/02_create_document_chunks.sql → tables/03_create_czech_fts.sql → tables/04_add_content_kind.sql. Spouští je configure_postgresql.py, vždy IF NOT EXISTS, nikdy DROP.',
        ],
      },
    ],
    files: ['postgres/Dockerfile', 'data/scripts/sql/tables/03_create_czech_fts.sql'],
  },

  {
    id: 'query',
    phase: 'retrieve',
    title: 'Dotaz a filtry',
    lead: 'Z dotazu se vyzobou prefixy jako `autor:` a `obec:`. SQL nepíše model, ale kód.',
    cost: 'local',
    tech: ['search_filters.py', 'parametrizované %s'],
    what: [
      'Filtr a sémantiku lze odlišit v jednom dotazu: "autor:Poul obec:Lednice hladina vody" — prefixy se vyzobou z textu, zbytek jde na vektory a fulltext.',
      'search_filters.py skládá WHERE jen z vlastního pevného slovníku prefixů (autor, klient, lokalita, obec, typ, org, od, do, doc, druh) a každou hodnotu posílá jako parametr %s.',
      'Textové filtry hledají podřetězec — autor:Poul trefí i "Mgr. Josefína Bízová, RNDr. Mgr. Ivan Poul, Ph.D."',
      'Neznámý prefix se nezahodí — zůstane součástí hledaného textu a vypíše se varování.',
    ],
    safeguard: [
      'Dotaz se záměrně nepřevádí na SQL modelem. Model si může vymyslet sloupec nebo vrátit věcně špatný výsledek bez chyby, a u geologických posudků je tichá chyba bezpečnostní problém — ze stejného důvodu extrakce nesmí nic domýšlet.',
    ],
    files: ['data/scripts/search_filters.py'],
  },
  {
    id: 'qembed',
    phase: 'retrieve',
    title: 'Embedding dotazu',
    lead: 'Jedno volání na dotaz, s jiným task_type než u chunků. Poslední dotazy drží cache.',
    cost: 'paid',
    tech: ['RETRIEVAL_QUERY', 'LRU 256'],
    what: [
      'embed_query() volá stejný model jako chunky, ale s task_type=RETRIEVAL_QUERY — obě strany páru (dokument/dotaz) musí sedět, jinak retrieval kvalita zkolabuje.',
      'search_service.py drží v paměti LRU cache posledních 256 embeddovaných dotazů; compare() navíc embedduje jednou pro všechny tři režimy naráz.',
      'Search je jedno embedding volání a kvóta je na požadavek za minutu — burst dotazů může narazit na 429; --mode fts se volání vyhne úplně.',
    ],
    files: ['data/scripts/search_service.py', 'data/scripts/gemini_auth.py'],
  },
  {
    id: 'branch-fts',
    phase: 'retrieve',
    title: 'Větev slov (fulltext)',
    lead: 'Dvě konfigurace naráz. Přísná varianta chce všechna slova, volnější váží vzácnost.',
    cost: 'sql',
    branch: 'fts',
    tech: ['websearch_to_tsquery', 'IDF'],
    what: [
      'Přísný režim fts: websearch_to_tsquery(czech, …) || websearch_to_tsquery(czech_literal, …). "||" nad tsquery je OR, takže obě konfigurace se OR-ují — ale slova uvnitř jedné konfigurace websearch_to_tsquery pořád AND-uje.',
      'Na golden sadě fts najde odpověď jen u 3 z 34 otázek, protože otázka málokdy má všechna svá slova v jednom chunku.',
      'fts_any (a fulltextová část rerankingu) je volnější: každé slovo dotazu se stane vlastní tsquery, sečte se váha IDF (ln(1 + (N−df+0,5)/(df+0,5))) chunků, které dané slovo obsahují, a ts_rank jen rozhoduje remízy.',
      'Bez IDF by "podzemní voda" (stovky chunků) přehlušilo jediné jméno místa, které identifikuje správný posudek.',
    ],
    numbers: [
      { label: 'fts recall@40', value: '0,09' },
      { label: 'fts_any recall@40', value: '0,88' },
    ],
    files: ['data/scripts/search_service.py'],
  },
  {
    id: 'branch-vector',
    phase: 'retrieve',
    title: 'Větev významu (vektory)',
    lead: 'Kosinová vzdálenost nad HNSW. Chunky bez vektoru, tedy přílohy, sem nepatří.',
    cost: 'sql',
    branch: 'vector',
    tech: ['pgvector <=>', 'hnsw.ef_search'],
    what: [
      'Řazení podle embedding <=> dotaz (kosinová vzdálenost) přes WHERE embedding IS NOT NULL — přílohové chunky bez vektoru se sem nedostanou nikdy.',
      'hnsw.ef_search se nastaví na počet řádků, které se natahují (min 40, max 1000), transakčně lokálně přes set_config.',
      'S metadatovým filtrem se vektorový dotaz nejdřív joinuje s documents a teprve pak řadí — stojí to HNSW index, ale je to správný kompromis: filtrování až po globálním top-N by mohlo vrátit nic.',
    ],
    numbers: [{ label: 'recall@40', value: '0,83' }],
    files: ['data/scripts/search_service.py'],
  },
  {
    id: 'rrf',
    phase: 'retrieve',
    title: 'Sloučení a výběr kandidátů',
    lead: 'RRF sloučí obě pořadí. Kandidáti jsou ale dvacet nejlepších z každé větve zvlášť.',
    cost: 'local',
    tech: ['RRF k = 60', '20 + 20 = 40'],
    what: [
      'Reciprocal Rank Fusion: skóre chunku je součet 1/(60 + pořadí) přes větve, ve kterých se objevil. Nahoře skončí to, co našly obě metody.',
      'Kandidáti pro reranking se ale neberou z fúzovaného top 40 — je to 20 nejlepších z vektoru a 20 nejlepších z volnějšího fulltextu, zvlášť.',
      'Fúze totiž systematicky nadržuje tomu, co našly obě větve, a vytlačuje úryvky, které najde jen jedna — typicky přílohy bez vektoru. Oprava přidala dvě správné odpovědi v měření.',
    ],
    blocks: [
      {
        kind: 'code',
        title: 'RRF (data/scripts/search_service.py)',
        code: `RRF_K = 60
hit["rrf_score"] += 1.0 / (RRF_K + rank)`,
      },
    ],
    numbers: [
      { label: 'RRF k', value: '60' },
      { label: 'kandidátů', value: '20 + 20 = 40' },
    ],
    files: ['data/scripts/search_service.py'],
  },
  {
    id: 'rerank',
    phase: 'retrieve',
    title: 'Reranking',
    lead: 'Gemini přečte 40 kandidátů s otázkou a každému dá známku 0–3 i důvod.',
    cost: 'paid',
    tech: ['Gemini', 'dávka 20 × 2', 'cache známek'],
    what: [
      '40 kandidátů se ohodnotí ve dvou paralelních voláních po 20. Škála: 3 = úryvek přímo obsahuje odpověď, 2 = obsahuje její část, 1 = souvisí s tématem, 0 = nesouvisí.',
      'Chunk o jiné lokalitě, vrtu nebo dokumentu než otázka dostane nejvýš 1, i kdyby jinak odpovídal na podobnou otázku.',
      'Známky se cachují dvouvrstvě: v paměti procesu (LRU 5000) pro běžící web demo, na disku (data/processed/answers/grades/) pro CLI a evaluaci napříč procesy — klíč drží model, otázku a otisk korpusu.',
      'Menší dávky nepomáhají: 20×2 trvá v mediánu 9,5 s, 10×4 8,5 s, 8×5 9,4 s — latence je hlavně na volání, ne na kandidáta. Menší dávky navíc mění samotné známky (29 ze 200 se posunulo), protože dávka je srovnávací množina.',
    ],
    safeguard: [
      'Text úryvků jsou data, ne pokyny — instrukce uvnitř úryvků se neprovádí. Stejné pravidlo jako u kontroly citací a u volání modelu pro odpověď.',
    ],
    gotchas: [
      {
        title: 'Známky nejsou plně reprodukovatelné',
        text: 'Ani při teplotě 0 nejsou známky stoprocentně stabilní — stejný chunk dostal 2 v jednom procesu a 3 v jiném. Hraniční chunk může přes bránu projít nebo ne podle běhu; evaluace se proto srovnává podle součtů, ne podle jednotlivých otázek.',
      },
    ],
    numbers: [
      { label: 'medián', value: '6 s (4–13 s)' },
      { label: 'cache: nová otázka', value: '7,1 s' },
      { label: 'cache: dřív hodnocená', value: '4 ms' },
    ],
    files: ['data/scripts/rerank_service.py', 'data/scripts/grade_cache.py'],
  },
  {
    id: 'gate',
    phase: 'retrieve',
    title: 'Brána relevance',
    lead: 'Známka 2 je práh. Když ji nikdo nepřekročí, model se vůbec nezavolá.',
    cost: 'local',
    tech: ['MIN_GRADE = 2'],
    what: [
      'Brána je jednoduchý predikát: grade is None or grade >= 2. Chunk bez známky (reranking neproběhl) projde automaticky.',
      'Zavřená brána znamená, že se odpovídací volání modelu vůbec nespustí — nejlevnější možná forma "nevím".',
      'Na golden sadě: brána pustila relevantní úryvek u 33 z 34 zodpověditelných otázek a nepustila nic u všech 6 nezodpověditelných.',
    ],
    numbers: [
      { label: 'práh', value: 'známka ≥ 2' },
      { label: 'propustila relevantní', value: '33 / 34' },
      { label: 'zavřela u nezodpověditelných', value: '6 / 6' },
    ],
    files: ['data/scripts/rerank_service.py'],
  },

  {
    id: 'context',
    phase: 'answer',
    title: 'Sestavení kontextu',
    lead: 'Nejvýš osm úryvků, tři z jednoho posudku. Míň kontextu je lepší kontext.',
    cost: 'local',
    tech: ['8 zdrojů', '10 000 tokenů', 'sousedé'],
    what: [
      'Nejvýš 8 úryvků, z jednoho posudku v prvním kole nejvýš 3, se stropem 10 000 tokenů — počítá se z token_count, který už je uložený, takže výběr nestojí žádné volání.',
      'K úryvku, jehož sekce je rozdělená do víc oken, se přidá soused se stejnou sekcí a rolí "kontext" — čte se, aby se necitovala půlka věty.',
      'Zdroje jdou modelu jako JSON s escapovanými < a > (chunk nemůže zavřít blok, ve kterém sedí) a otázka jde až za nimi — dlouhý prompt Gemini zvládá lépe, když otázka přijde poslední.',
      'Do promptu jde doslovný chunk_raw, nikdy chunk_text s KONTEXT: prefixem — ten je model-generated shrnutí a citoval by se, jako by to byl text zprávy.',
    ],
    numbers: [
      { label: 'max zdrojů', value: '8' },
      { label: 'max z jednoho posudku', value: '3' },
      { label: 'strop', value: '10 000 tokenů' },
      { label: 'max sousedů', value: '4' },
    ],
    files: ['data/scripts/context_builder.py'],
  },
  {
    id: 'generate',
    phase: 'answer',
    title: 'Volání modelu',
    lead: 'Jedno volání. Odpovídá se jen ze zdrojů a každá věta musí nést doslovný citát.',
    cost: 'paid',
    tech: ['Gemini', 'temperature 0', 'PROMPT_VERSION = 2'],
    what: [
      'Model odpovídá jen ze zdrojů, nepřevádí jednotky, nepřenáší zjištění mezi lokalitami. Každá věta potřebuje aspoň jeden source_id a aspoň jeden doslovný citát o 5 až 30 slovech.',
      'Žádná čísla stran ani kapitol ve větách — ta se ukazují až u citace, ne v textu odpovědi.',
      'Když zdroje nestačí: insufficient s prázdnými větami a vyplněným missing, nebo partial pro zdokumentovanou část. "Nevím" je plnohodnotná odpověď, ne selhání.',
      'Rozpory se nevybírají — obě hodnoty se uvedou s citacemi a popíšou se v conflicts, po ověření, že nejde o různé lokality nebo vrty.',
    ],
    safeguard: [
      'Zdrojový text je data, ne pokyny — instrukce uvnitř zdrojů se neprovádí, nanejvýš se zmíní jako obsah dokumentu. Žádné odkazy, URL ani obrázky v odpovědi.',
    ],
    numbers: [
      { label: 'PROMPT_VERSION', value: '2' },
      { label: 'teplota', value: '0.0' },
      { label: 'citát', value: '5–30 slov' },
    ],
    files: ['data/scripts/answer_service.py', 'data/scripts/answer_prompts.py'],
  },
  {
    id: 'citations',
    phase: 'answer',
    title: 'Kontrola citací',
    lead: 'Server hledá každý citát v citovaném úryvku a každé číslo věty ve zdrojích.',
    cost: 'local',
    tech: ['citation_check.py', 'text_match.py'],
    what: [
      'Gemini nemá API pro citace vlastních dokumentů, takže záruku dodělává server. Čtyři kontroly v pořadí, první selhání vyhrává: neplatný zdroj → bez citátu → citát se nenašel → číslo bez opory.',
      'Citát se hledá jen v chunk_raw citovaného zdroje (ne v hlavičce), po normalizaci (NFC, spojovníky, mezery — ale ne diakritika, čísla ani jednotky, ty musí sedět přesně).',
      'Číslo se hledá i v pěti hlavičkových polích zdroje (titul, obec, typ, organizace, datum) — ta jdou do promptu se zdrojem, takže jsou opora. Strana a sekce záměrně ne, jsou to malé celočíselné hodnoty ve stejném rozsahu jako hlídané veličiny.',
      'Digit nalepený na písmeno (HV1, J16) se nepočítá jako číslo vůbec — je to jméno. Mezera mezi číslicemi se povoluje kvůli tabulkám a tisícovkám.',
      'Věta, která neprojde, se označí a stav odpovědi klesne na partial.',
    ],
    numbers: [{ label: 'prošlo kontrolou', value: '72 / 78 vět' }],
    files: ['data/scripts/citation_check.py', 'data/scripts/text_match.py'],
  },
  {
    id: 'output',
    phase: 'answer',
    title: 'Co dostane uživatel',
    lead: 'Věty s citacemi, zdroje, odkaz do PDF na stranu — a stav, který může být „nevím".',
    cost: 'sql',
    artifact: 'asked.jsonl + cache odpovědí',
    tech: ['FastAPI', 'server-sent events'],
    what: [
      'Čtyři stavy: answered, partial, insufficient, no_evidence — poslední z nich je jediný, který model vůbec neviděl (brána byla zavřená).',
      'POST /api/answer/stream posílá kroky přes server-sent events, jak k nim server dochází — deset až třicet sekund u jednoho spinneru vypadá jako zaseknutá stránka, kroky s čísly ne.',
      'Odpověď se cachuje podle otázky, filtrů, nastavení, modelu, verze promptu a otisku manifestu — stejná otázka je pak za 0,55 s místo 22,9 s. Nový ingest cache zneplatní.',
      'GET /api/documents/{id}/pdf otevře zdrojové PDF na straně, kterou citace jmenuje — jméno souboru se řeší jen uvnitř REPORTS_INPUT_DIR, traversal mimo něj nejde.',
      'Každá otázka se zapíše do asked.jsonl s větami, citáty a výsledkem kontroly — surovina pro budoucí rozšíření zlaté sady, protože skutečné otázky jsou lepší než vymyšlené.',
    ],
    safeguard: [
      'API nemá autentizaci — zabezpečení je jen v tom, že je v Compose publikované jen na loopback (127.0.0.1) a posudky jsou interní dokumenty organizace.',
    ],
    numbers: [
      { label: 'cache odpovědi', value: '22,9 s → 0,55 s' },
      { label: 'medián na otázku', value: '13,8 s' },
    ],
    files: ['data/scripts/search_api.py', 'data/scripts/answer_log.py', 'data/scripts/answer_cache.py'],
  },
]

/** Questions that cut across the whole pipeline rather than sitting at one step. */
export const TOPICS: Topic[] = [
  {
    id: 'eval',
    tag: 'měření',
    title: 'Měření kvality',
    lead: 'Čtyřicet českých otázek, z toho šest bez odpovědi v korpusu.',
    tech: ['golden.yaml', 'recall@k', 'MRR'],
    what: [
      'data/eval/golden.yaml: 40 otázek — 12 exact (kódy, označení), 11 paraphrase, 6 negative (bez odpovědi v korpusu), 5 morphology, 4 annex, 2 multi (odpověď ve více dokumentech).',
      'Relevance se určuje podle textu (text_match.py ignoruje velikost písmen, zdvojené mezery, druh pomlčky), ne podle chunk_id — sada přežije přechunkování.',
      'eval_retrieval.py měří recall@5/10/40 a MRR pro každý režim; eval_answers.py měří, jestli odpověď citovala očekávaný úryvek, kolik vět prošlo kontrolou a jestli systém mlčel tam, kde korpus odpověď nemá.',
      '--check ověří sadu proti databázi zdarma — výňatek, který nic nenajde, by se jinak tiše počítal jako nenalezený.',
    ],
    blocks: [
      {
        kind: 'table',
        title: 'Retrieval (13. 9. 2026, 34 zodpověditelných otázek)',
        table: {
          head: ['režim', 'recall@5', 'recall@40', 'MRR', 'odpověď mimo top 40'],
          rows: [
            ['fts', '0,04', '0,09', '0,06', '31 z 34'],
            ['vector', '0,62', '0,83', '0,53', '5 z 34'],
            ['hybrid', '0,66', '0,87', '0,54', '4 z 34'],
            ['fts_any', '0,69', '0,88', '0,53', '4 z 34'],
            ['rerank', '0,92', '0,96', '0,79', '1 z 34'],
          ],
        },
      },
      {
        kind: 'table',
        title: 'Odpovědi (15. 9. 2026, 40 otázek)',
        table: {
          head: ['co se měřilo', 'výsledek'],
          rows: [
            ['odpovězeno / částečně / nedostatek podkladů / bez podkladů', '28 / 4 / 2 / 6'],
            ['očekávaný úryvek byl v kontextu', '34 z 34'],
            ['odpověď ho i citovala', '31 z 34'],
            ['věty, které prošly kontrolou citací', '72 z 78'],
            ['otázky bez odpovědi: systém mlčel', '6 z 6'],
            ['vymyšlená odpověď', '0'],
            ['medián času na otázku', '13,8 s'],
          ],
        },
      },
      {
        kind: 'table',
        title: 'Kolik kandidátů se hodnotí (16. 9. 2026)',
        table: {
          head: ['kandidátů', 'recall@5', 'recall@40', 'MRR', 'brána pustila'],
          rows: [
            ['40', '0,924', '0,956', '0,806', '33 z 34'],
            ['24', '0,894', '0,926', '0,792', '32 z 34'],
          ],
        },
      },
      {
        kind: 'note',
        title: 'Pozor při srovnávání běhů',
        text: [
          'Známky rerankeru nejsou plně reprodukovatelné ani při teplotě 0, takže jednotlivé běhy kolísají o pár setin — srovnávají se podle součtů přes celou sadu, ne podle jedné otázky.',
        ],
      },
    ],
    files: ['data/eval/golden.yaml', 'data/scripts/eval_retrieval.py', 'data/scripts/eval_answers.py'],
  },
  {
    id: 'security',
    tag: 'bezpečnost',
    title: 'Bezpečnostní opatření',
    lead: 'Kde všude se hlídá, aby systém nelhal a aby se dokumenty nedostaly ven.',
    tech: ['grounding', 'kontrola citací', 'injection_scan'],
    what: [
      'Extrakce je striktně groundovaná — žádné odvozování, žádné dopočítávání z obecných znalostí. U geologického posudku je vymyšlená hladina podzemní vody bezpečnostní chyba, ne kosmetická.',
      'Dotaz se nepřevádí na SQL modelem — search_filters.py skládá WHERE jen z vlastního pevného slovníku a hodnoty posílá parametrizovaně. Model může vymyslet sloupec nebo vrátit tiše špatný výsledek.',
      'Zdrojový text (chunky, extrakce) je do promptu vždy data, ne pokyny — grader i model pro odpověď mají explicitní instrukci instrukce uvnitř zdrojů neprovádět.',
      'injection_scan.py (v check_pipeline.py) hlásí, když nějaký chunk mluví k modelu, ne ke čtenáři — přepsání pokynů, novou roli, diktovanou odpověď, napodobený systémový prompt. Není to obrana (ta je v tom, že zdroje jsou data), ale jediné místo, kde se to člověk dozví.',
      'citation_check.py je poslední pojistka nad odpovědí: každý citát musí být doslova v citovaném úryvku, každé číslo věty musí mít oporu ve zdrojích.',
      'PDF endpoint řeší jen jméno souboru uvnitř REPORTS_INPUT_DIR — resolved candidate musí mít stejného rodiče jako vstupní adresář, jinak vrátí 404. Traversal mimo adresář nejde.',
      'API nemá autentizaci ani autorizaci — jediná ochrana je publikování portu jen na loopback (127.0.0.1:8010) v Compose a to, že posudky jsou interní.',
      'Posudky se do gitu neukládají (data/PDFs je gitignorované), přihlašovací údaje žijí jen v .env, verzuje se jen .env.template.',
    ],
    numbers: [{ label: 'čistých dokumentů proti injection_scan', value: '16 / 16' }],
    files: ['data/scripts/search_filters.py', 'data/scripts/citation_check.py', 'data/scripts/injection_scan.py', 'data/scripts/search_api.py'],
  },
  {
    id: 'runtime',
    tag: 'provoz',
    title: 'Provoz a nasazení',
    lead: 'Tři kontejnery, dvě cache a několik pastí, do kterých se tu už šláplo.',
    tech: ['Docker Compose', 'nginx', 'PostgreSQL 17'],
    what: [
      'Tři služby: postgres (vlastní obraz s pgvector a hunspell-cs), api (FastAPI, Dockerfile.api), frontend (React, servírováno nginxem). name: vectorsearch v compose souboru brání recyklaci cizích kontejnerů.',
      'postgres publikuje 5432 na všech rozhraních; api a frontend jen na 127.0.0.1 — posudky jsou interní a API nemá autentizaci.',
      'Manifest se do API kontejneru mountuje read-only, protože oba cache (odpovědí i známek) klíčují na jeho otisk. Bez mountu by kontejner otiskl prázdný korpus a nesdílel nic s příkazovou řádkou.',
      'nginx.conf čeká na /api/ 300 s — odpověď trvá typicky 10–30 s, ale pomalé volání Gemini bylo vidět přes dvě minuty. Kratší timeout než řetěz za ním vypadá přesně jako spadlý endpoint.',
    ],
    gotchas: [
      {
        title: '--no-deps je nutné',
        text: 'docker compose up --build api frontend bez --no-deps přestaví i obraz PostgreSQL jako závislost — a pokud se obraz změní, vytvoří databázový kontejner znovu. Data na disku přežijí, otevřená spojení ne. Jeden evaluační běh takhle zemřel uprostřed.',
      },
      {
        title: 'Bind mount drží data',
        text: 'deploy/local/data/postgres nikdy nemazat a nepouštět docker compose down -v ani --remove-orphans bez rozmyslu — databáze obsahuje reálné dokumenty.',
      },
    ],
    files: ['deploy/local/docker-compose.yml', 'frontend/nginx.conf', 'postgres/Dockerfile', 'data/scripts/Dockerfile.api'],
  },
  {
    id: 'schema',
    tag: 'schéma',
    title: 'Doladění schématu z extra_fields',
    lead: 'Extrakční schéma je provizorní schválně. Teď je poprvé dost dat ho dodělat.',
    tech: ['extra_fields', 'missing_fields', 'SCHEMA_VERSION'],
    what: [
      'Schéma bylo napsané dřív, než existoval jediný reálný posudek. report_type je proto volný text, ne Literal, a extra_fields sbírá vše, co schéma nepokrývá.',
      'Teď je poprvé dost dat: cislo_zakazky, cislo_geofond, hydrogeologicky_rajon, souradnice_vrtu_sjtsk, hloubka_vrtu, vystroj_vrtu se opakují napříč dokumenty.',
      'Aggregace se dělá v SQL nad extraction_json — časté klíče v extra_fields jsou pole, která schématu chybí; časté položky v missing_fields jsou pole, která do schématu možná vůbec nepatří.',
    ],
    blocks: [
      {
        kind: 'code',
        title: 'Agregace extra_fields a missing_fields',
        code: `SELECT jsonb_array_elements(extraction_json->'extra_fields')->>'key' AS field,
       count(*)
FROM documents GROUP BY 1 ORDER BY 2 DESC;

SELECT jsonb_array_elements_text(extraction_json->'missing_fields') AS field,
       count(*)
FROM documents GROUP BY 1 ORDER BY 2 DESC;`,
      },
      {
        kind: 'text',
        title: 'Postup (.claude/skills/data-ingestion/SKILL.md)',
        text: [
          '1. Nové posudky do data/PDFs. 2. extract_reports.py --markdown-only bez placení, přečíst Markdown ručně. 3. ingest.py na hrstce posudků. 4. Agregovat extra_fields a missing_fields (SQL výše). 5. Upravit schemas.py: přidat povýšená pole, zúžit report_type na Literal, zvednout SCHEMA_VERSION. 6. Přidat migraci s ALTER TABLE … ADD COLUMN IF NOT EXISTS a zpětné vyplnění z extraction_json, namapovat sloupce v import_reports.py. 7. configure_postgresql.py && ingest.py.',
        ],
      },
      {
        kind: 'note',
        title: 'Co to stojí',
        text: [
          'Re-extrakce čte cachovaný Markdown, žádné PDF se neparsuje znovu. Ale zvednutí SCHEMA_VERSION znovu spustí extrakci, chunking, embedding i import pro všech 16 dokumentů — a dvě ze čtyř fází jsou placené.',
        ],
      },
    ],
    files: ['data/scripts/schemas.py', '.claude/skills/data-ingestion/SKILL.md'],
  },
  {
    id: 'open',
    tag: 'co zbývá',
    title: 'Otevřené věci a další práce',
    lead: 'Co je známé a neřešené, co by to stálo a proč se to zatím nechalo být.',
    tech: ['svazky', 'OCR', 'prozaická příloha'],
    what: [
      'Hotová a ověřená je celá cesta od PDF k odpovědi. Dvě věci zbývají a obě stojí placený přeběh celého korpusu, takže jsou rozhodnutím, ne běžnou prací.',
      '1. Rozpad svazků na dílčí zprávy — největší otevřená strukturální věc. GF_P188240_ZZ Sedmirohé je jedenáct zpráv pod jedním přebalem (přebaly na stranách 1, 22, 43, 89, 108, 131, 150, 173, 197, 220, 242), Metan jih pět. _extract_toc bere první název pro dané číslo napříč všemi obsahy, takže jedenáct osnov splyne v jednu — 59 chunků Sedmirohé a 21 Metan jih sedí pod nadpisem z cizí dílčí zprávy.',
      '2. Doladění extrakčního schématu — viz karta "Doladění schématu z extra_fields".',
    ],
    blocks: [
      {
        kind: 'table',
        title: 'Menší otevřené věci',
        table: {
          head: ['co', 'stav', 'proč se to nechalo být'],
          rows: [
            ['Tři skeny bez OCR', 'mimo korpus', 'OCR je krok mimo pipeline; běh je ohlásí jako skipped a pokračuje dál'],
            ['ZZ_Pazderna: 34 chunků pod "6.1 SEZNAM NOREM"', 'známé, neřešené', 'hranice přílohy se hledá jako formulářová strana; když žádná za posledním nadpisem není, nemá na co ukázat'],
            ['Monitoring: chunk #0 bez sekce', 'záměr pravidla', '"žádný titulek je lepší než špatný" — check_pipeline to hlásí jako chybu, i když jde jen o front matter'],
          ],
        },
      },
    ],
    files: ['README.md', 'CLAUDE.md'],
  },
]

export const DETAILS: Detail[] = [...STEPS, ...TOPICS]

/** The step or topic behind a diagram box, or undefined for an unknown id. */
export function detailOf(id: string): Detail | undefined {
  return DETAILS.find((item) => item.id === id)
}

/** Steps of one phase, in pipeline order, with the number shown on the box. */
export function stepsOfPhase(phase: PhaseId): { step: Step; number: number }[] {
  return STEPS.map((step, index) => ({ step, number: index + 1 })).filter((item) => item.step.phase === phase)
}
