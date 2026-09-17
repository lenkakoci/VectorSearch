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
    what: [],
    files: ['data/scripts/pipeline_common.py'],
  },
  {
    id: 'text',
    phase: 'prep',
    title: 'Čtení PDF',
    lead: 'Jeden průchod pdfminerem po stranách. Z téhož průchodu je text i mapa stran.',
    cost: 'local',
    artifact: '<stem>.pages.json',
    tech: ['pdfminer.six', 'LAParams'],
    what: [],
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
    what: [],
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
    what: [],
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
    what: [],
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
    what: [],
    files: ['data/scripts/extract_reports.py', 'data/scripts/schemas.py'],
  },
  {
    id: 'chunk',
    phase: 'prep',
    title: 'Chunking podle sekcí',
    lead: 'Cesta nadpisů se stane citací. Velká sekce se rozdělí do oken s překryvem.',
    cost: 'local',
    tech: ['800 / 100 / 150 tokenů', 'tiktoken', 'CHUNKER_VERSION = 4'],
    what: [],
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
    what: [],
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
    what: [],
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
    what: [],
    files: ['data/scripts/manifest.py', 'data/scripts/ingest.py'],
  },
  {
    id: 'check',
    phase: 'prep',
    title: 'Kontrola výsledku',
    lead: 'Nic nezapisuje, nic nestojí. Hledá tiché chyby — a věty, které mluví k modelu.',
    cost: 'local',
    tech: ['check_pipeline.py', 'injection_scan.py'],
    what: [],
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
    what: [],
    files: ['data/scripts/sql/tables/01_create_documents.sql', 'data/scripts/sql/tables/02_create_document_chunks.sql'],
  },
  {
    id: 'index',
    phase: 'store',
    title: 'Indexy a trigger',
    lead: 'HNSW na význam, GIN na slova. Tsvector plní trigger, ne generovaný sloupec.',
    cost: 'sql',
    tech: ['pgvector HNSW', 'GIN', 'BEFORE INSERT OR UPDATE'],
    what: [],
    files: ['data/scripts/sql/tables/02_create_document_chunks.sql', 'data/scripts/sql/tables/04_add_content_kind.sql'],
  },
  {
    id: 'czech',
    phase: 'store',
    title: 'Český fulltext',
    lead: 'PostgreSQL nemá český stemmer. Doplní ho hunspell — a indexují se dvě konfigurace naráz.',
    cost: 'sql',
    tech: ['hunspell-cs', 'czech', 'czech_literal'],
    what: [],
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
