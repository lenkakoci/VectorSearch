import clsx from 'clsx'
import { Info, MessagesSquare, Search, Settings2, SlidersHorizontal, Workflow } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { ActiveFilters } from './components/ActiveFilters'
import { ArchitectureView } from './components/ArchitectureView'
import { AskView } from './components/AskView'
import { CompareView } from './components/CompareView'
import { DebugPanel } from './components/DebugPanel'
import { FilterPanel } from './components/FilterPanel'
import { ModeSwitch } from './components/ModeSwitch'
import { AskOptions, SearchOptions, ToggleButton } from './components/Options'
import { ResultList } from './components/ResultList'
import { SearchBar } from './components/SearchBar'
import { useAnswer } from './hooks/useAnswer'
import { useSearch } from './hooks/useSearch'
import { DEMO_QUESTIONS } from './lib/answers'
import { countActive, emptyFilters, toRequestFilters, type FilterState } from './lib/filters'
import { MODE_INFO } from './lib/modes'
import { api } from './services/api'
import type { Facets, Health, View } from './types'

type Tab = 'search' | 'ask' | 'architecture'

const TABS: { id: Tab; label: string; icon: typeof Search }[] = [
  { id: 'search', label: 'Vyhledávání', icon: Search },
  { id: 'ask', label: 'Zeptat se dokumentů', icon: MessagesSquare },
  { id: 'architecture', label: 'Architektura', icon: Workflow },
]

const SUBTITLE: Record<Tab, string> = {
  search: 'Demo vyhledávání v geologických posudcích: slova × význam × obojí × reranking',
  ask: 'Odpověď složená jen z nalezených úryvků, u každé věty zdroj a ověřený citát',
  architecture: 'Celá pipeline na jedné obrazovce, krok po kroku k rozkliknutí',
}

export default function App() {
  const [tab, setTab] = useState<Tab>('search')
  const [query, setQuery] = useState('')
  const [question, setQuestion] = useState('')
  const [view, setView] = useState<View>('compare')
  const [limit, setLimit] = useState(5)
  const [rerank, setRerank] = useState(false)
  const [maxSources, setMaxSources] = useState(8)
  const [minGrade, setMinGrade] = useState(2)
  const [neighbours, setNeighbours] = useState(true)
  const [fresh, setFresh] = useState(false)
  const [filters, setFilters] = useState<FilterState>(emptyFilters)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [optionsOpen, setOptionsOpen] = useState(false)
  const [debugOpen, setDebugOpen] = useState(false)
  const [expertOpen, setExpertOpen] = useState(false)
  const [facets, setFacets] = useState<Facets | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [backendError, setBackendError] = useState<string | null>(null)
  const { state, run } = useSearch()
  const { state: answerState, ask } = useAnswer()
  const lastQuery = useRef<string | null>(null)

  useEffect(() => {
    api.facets().then(setFacets).catch((error: Error) => setBackendError(error.message))
    api.health().then(setHealth).catch(() => setHealth(null))
  }, [])

  const submit = (text: string) => {
    const trimmed = text.trim()
    if (!trimmed) return
    lastQuery.current = trimmed
    void run(trimmed, view, toRequestFilters(filters), limit, rerank)
  }

  const submitQuestion = (text: string) => {
    const trimmed = text.trim()
    if (!trimmed) return
    void ask(trimmed, toRequestFilters(filters), {
      max_sources: maxSources,
      min_grade: minGrade,
      neighbours,
      fresh,
    })
  }

  // A change of mode, filter, limit or reranking re-runs the last query, so the
  // demo can flip between views without retyping. Query embeddings and grades
  // are cached server side, so this costs SQL and only the grades not seen yet.
  // A question is never re-sent this way: answering always costs a model call.
  const first = useRef(true)
  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    if (tab === 'search' && lastQuery.current) void run(lastQuery.current, view, toRequestFilters(filters), limit, rerank)
  }, [tab, view, filters, limit, rerank, run])

  const activeFilters = countActive(filters)
  const requestFilters = toRequestFilters(filters)
  const asking = answerState.status === 'loading'
  const explain = (
    <p className="flex max-w-4xl flex-1 items-start gap-2 rounded-md border border-brand-100 bg-brand-50 px-3 py-2 text-sm text-brand-900">
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-brand-500" />
      <span>{tab === 'search' ? MODE_INFO[view].explain : MODE_INFO.rerank.explain}</span>
    </p>
  )

  return (
    <div className="min-h-screen">
      <header className="bg-brand-900 text-white shadow">
        <div className="mx-auto flex max-w-[96rem] flex-wrap items-center gap-x-8 gap-y-2 px-4 md:px-6">
          <div className="flex items-baseline gap-2 py-3">
            <span className="text-xl font-bold tracking-tight">VectorSearch</span>
            <span className="text-sm text-brand-200">geologické posudky</span>
          </div>
          <nav className="flex flex-1 flex-wrap self-stretch" role="tablist">
            {TABS.map((item) => {
              const Icon = item.icon
              const active = item.id === tab
              return (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setTab(item.id)}
                  className={clsx(
                    'flex items-center gap-2 border-b-4 px-4 py-3 text-sm font-medium transition',
                    active ? 'border-leaf-500 bg-white/10 text-white' : 'border-transparent text-brand-100 hover:bg-white/5 hover:text-white',
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </button>
              )
            })}
          </nav>
          <p className={clsx('py-3 text-xs', backendError && !health ? 'font-medium text-clay-200' : 'text-brand-200')}>
            {health
              ? `${health.documents} dokumentů · ${health.chunks} chunků · ${health.chunks_with_vector} s vektorem`
              : backendError
                ? 'API nedostupné'
                : ''}
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-[96rem] space-y-4 p-4 md:p-6">
        <p className="text-sm text-slate-600">{SUBTITLE[tab]}</p>

        {backendError && (
          <div className="rounded-lg border border-clay-200 bg-clay-50 p-3 text-sm text-clay-700">
            Nepodařilo se načíst číselníky filtrů: {backendError}. Běží API na portu 8010?
          </div>
        )}

        {tab === 'search' && <SearchBar query={query} loading={state.status === 'loading'} onChange={setQuery} onSubmit={submit} />}
        {tab === 'ask' && (
          <SearchBar
            query={question}
            loading={asking}
            onChange={setQuestion}
            onSubmit={submitQuestion}
            placeholder="Na co se chcete zeptat? Např. Kolik vrtů se v Roudně navrhuje?"
            label="Na co se chcete zeptat?"
            submitLabel="Zeptat se"
            loadingLabel="Odpovídám…"
            suggestions={DEMO_QUESTIONS.map((demo) => ({ query: demo.question, why: demo.why }))}
            hint={false}
          />
        )}

        {tab !== 'architecture' && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              {tab === 'search' ? <ModeSwitch view={view} onChange={setView} /> : explain}
              <div className="flex flex-wrap items-center gap-2">
                <ToggleButton
                  icon={<Settings2 className="h-4 w-4" />}
                  label={tab === 'search' ? 'Nastavení' : 'Pokročilé'}
                  open={optionsOpen}
                  onClick={() => setOptionsOpen((value) => !value)}
                />
                <ToggleButton
                  icon={<SlidersHorizontal className="h-4 w-4" />}
                  label={tab === 'search' ? 'Filtry' : 'Omezit podklady'}
                  open={filtersOpen}
                  count={activeFilters}
                  onClick={() => setFiltersOpen((value) => !value)}
                />
              </div>
            </div>
            {tab === 'search' && explain}
            {optionsOpen && tab === 'search' && (
              <SearchOptions limit={limit} onLimit={setLimit} rerank={rerank} onRerank={setRerank} compare={view === 'compare'} />
            )}
            {optionsOpen && tab === 'ask' && (
              <AskOptions
                maxSources={maxSources}
                onMaxSources={setMaxSources}
                minGrade={minGrade}
                onMinGrade={setMinGrade}
                neighbours={neighbours}
                onNeighbours={setNeighbours}
                fresh={fresh}
                onFresh={setFresh}
              />
            )}
          </div>
        )}

        {tab !== 'architecture' && filtersOpen && <FilterPanel facets={facets} state={filters} onChange={setFilters} />}
        {tab !== 'architecture' && <ActiveFilters state={filters} facets={facets} onChange={setFilters} />}

        {tab === 'ask' && (
          <AskView state={answerState} expertOpen={expertOpen} onExpert={setExpertOpen} />
        )}

        {tab === 'architecture' && <ArchitectureView />}

        {tab === 'search' && (
          <>
            {state.status === 'error' && (
              <div className="rounded-lg border border-clay-200 bg-clay-50 p-3 text-sm text-clay-700">
                {state.error}
                {state.error?.startsWith('503') && view !== 'fts' && (
                  <button type="button" onClick={() => setView('fts')} className="ml-2 underline">
                    přepnout na fulltext
                  </button>
                )}
              </div>
            )}

            {state.status === 'idle' && (
              <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-slate-500">
                Zadejte dotaz nebo klikněte na některý z ukázkových. Režim „Porovnat“ ukáže stejný dotaz několika způsoby vedle sebe.
              </div>
            )}

            {state.status !== 'idle' && state.status !== 'error' && (
              <div className={state.status === 'loading' ? 'opacity-50 transition' : ''}>
                {state.view === 'compare' && state.compare && <CompareView data={state.compare} filters={requestFilters} />}
                {state.view !== 'compare' && state.single && (
                  <div className="space-y-2">
                    <p className="text-xs text-slate-500">
                      {MODE_INFO[state.single.mode].label}: {state.single.hits.length} výsledků pro „{state.single.query}“
                      {state.single.debug.fts_candidates != null && state.single.mode === 'hybrid' && (
                        <>
                          {' '}· kandidátů: vektor {state.single.debug.vector_candidates}, fulltext {state.single.debug.fts_candidates}
                        </>
                      )}
                      {state.single.debug.rerank && (
                        <>
                          {' '}· {state.single.debug.rerank.passed} z {state.single.debug.rerank.candidates} kandidátů má známku aspoň{' '}
                          {state.single.debug.rerank.min_grade}
                        </>
                      )}
                    </p>
                    <ResultList response={state.single} />
                  </div>
                )}
              </div>
            )}

            <DebugPanel state={state} open={debugOpen} onToggle={setDebugOpen} />
          </>
        )}
      </main>
    </div>
  )
}
