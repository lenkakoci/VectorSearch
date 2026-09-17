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
    what: [],
    files: ['data/scripts/search_filters.py'],
  },
  {
    id: 'qembed',
    phase: 'retrieve',
    title: 'Embedding dotazu',
    lead: 'Jedno volání na dotaz, s jiným task_type než u chunků. Poslední dotazy drží cache.',
    cost: 'paid',
    tech: ['RETRIEVAL_QUERY', 'LRU 256'],
    what: [],
    files: ['data/scripts/search_service.py'],
  },
  {
    id: 'branch-fts',
    phase: 'retrieve',
    title: 'Větev slov (fulltext)',
    lead: 'Dvě konfigurace naráz. Přísná varianta chce všechna slova, volnější váží vzácnost.',
    cost: 'sql',
    branch: 'fts',
    tech: ['websearch_to_tsquery', 'IDF'],
    what: [],
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
    what: [],
    files: ['data/scripts/search_service.py'],
  },
  {
    id: 'rrf',
    phase: 'retrieve',
    title: 'Sloučení a výběr kandidátů',
    lead: 'RRF sloučí obě pořadí. Kandidáti jsou ale dvacet nejlepších z každé větve zvlášť.',
    cost: 'local',
    tech: ['RRF k = 60', '20 + 20 = 40'],
    what: [],
    files: ['data/scripts/search_service.py'],
  },
  {
    id: 'rerank',
    phase: 'retrieve',
    title: 'Reranking',
    lead: 'Gemini přečte 40 kandidátů s otázkou a každému dá známku 0–3 i důvod.',
    cost: 'paid',
    tech: ['Gemini', 'dávka 20 × 2', 'cache známek'],
    what: [],
    files: ['data/scripts/rerank_service.py', 'data/scripts/grade_cache.py'],
  },
  {
    id: 'gate',
    phase: 'retrieve',
    title: 'Brána relevance',
    lead: 'Známka 2 je práh. Když ji nikdo nepřekročí, model se vůbec nezavolá.',
    cost: 'local',
    tech: ['MIN_GRADE = 2'],
    what: [],
    files: ['data/scripts/rerank_service.py'],
  },

  {
    id: 'context',
    phase: 'answer',
    title: 'Sestavení kontextu',
    lead: 'Nejvýš osm úryvků, tři z jednoho posudku. Míň kontextu je lepší kontext.',
    cost: 'local',
    tech: ['8 zdrojů', '10 000 tokenů', 'sousedé'],
    what: [],
    files: ['data/scripts/context_builder.py'],
  },
  {
    id: 'generate',
    phase: 'answer',
    title: 'Volání modelu',
    lead: 'Jedno volání. Odpovídá se jen ze zdrojů a každá věta musí nést doslovný citát.',
    cost: 'paid',
    tech: ['Gemini', 'temperature 0', 'PROMPT_VERSION = 2'],
    what: [],
    files: ['data/scripts/answer_service.py', 'data/scripts/answer_prompts.py'],
  },
  {
    id: 'citations',
    phase: 'answer',
    title: 'Kontrola citací',
    lead: 'Server hledá každý citát v citovaném úryvku a každé číslo věty ve zdrojích.',
    cost: 'local',
    tech: ['citation_check.py', 'text_match.py'],
    what: [],
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
    what: [],
    files: ['data/scripts/search_api.py', 'data/scripts/answer_log.py'],
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
    what: [],
    files: ['data/eval/golden.yaml', 'data/scripts/eval_retrieval.py', 'data/scripts/eval_answers.py'],
  },
  {
    id: 'security',
    tag: 'bezpečnost',
    title: 'Bezpečnostní opatření',
    lead: 'Kde všude se hlídá, aby systém nelhal a aby se dokumenty nedostaly ven.',
    tech: ['grounding', 'kontrola citací', 'injection_scan'],
    what: [],
    files: ['data/scripts/search_filters.py', 'data/scripts/citation_check.py', 'data/scripts/injection_scan.py'],
  },
  {
    id: 'runtime',
    tag: 'provoz',
    title: 'Provoz a nasazení',
    lead: 'Tři kontejnery, dvě cache a několik pastí, do kterých se tu už šláplo.',
    tech: ['Docker Compose', 'nginx', 'PostgreSQL 17'],
    what: [],
    files: ['deploy/local/docker-compose.yml', 'frontend/nginx.conf', 'postgres/Dockerfile'],
  },
  {
    id: 'schema',
    tag: 'schéma',
    title: 'Doladění schématu z extra_fields',
    lead: 'Extrakční schéma je provizorní schválně. Teď je poprvé dost dat ho dodělat.',
    tech: ['extra_fields', 'missing_fields', 'SCHEMA_VERSION'],
    what: [],
    files: ['data/scripts/schemas.py', '.claude/skills/data-ingestion/SKILL.md'],
  },
  {
    id: 'open',
    tag: 'co zbývá',
    title: 'Otevřené věci a další práce',
    lead: 'Co je známé a neřešené, co by to stálo a proč se to zatím nechalo být.',
    tech: ['svazky', 'OCR', 'prozaická příloha'],
    what: [],
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
