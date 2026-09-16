import clsx from 'clsx'
import { MessagesSquare, Search, SlidersHorizontal } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { ActiveFilters } from './components/ActiveFilters'
import { AskView } from './components/AskView'
import { CompareView } from './components/CompareView'
import { DebugPanel } from './components/DebugPanel'
import { FilterPanel } from './components/FilterPanel'
import { ModeSwitch } from './components/ModeSwitch'
import { ResultList } from './components/ResultList'
import { SearchBar } from './components/SearchBar'
import { useAnswer } from './hooks/useAnswer'
import { useSearch } from './hooks/useSearch'
import { DEMO_QUESTIONS } from './lib/answers'
import { countActive, emptyFilters, toRequestFilters, type FilterState } from './lib/filters'
import { MODE_INFO } from './lib/modes'
import { api } from './services/api'
import type { Facets, Health, View } from './types'

type Tab = 'search' | 'ask'

const TABS: { id: Tab; label: string; hint: string; icon: typeof Search }[] = [
  { id: 'search', label: 'Vyhledávání', hint: 'najde pasáže', icon: Search },
  { id: 'ask', label: 'Zeptat se dokumentů', hint: 'složí odpověď s citacemi', icon: MessagesSquare },
]

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

  return (
    <div className="mx-auto max-w-[96rem] space-y-4 p-4 md:p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">VectorSearch</h1>
          <p className="text-sm text-slate-500">
            {tab === 'search'
              ? 'Demo vyhledávání v geologických posudcích: slova × význam × obojí × reranking'
              : 'Odpověď složená jen z nalezených úryvků, u každé věty zdroj a ověřený citát'}
          </p>
        </div>
        <p className="text-xs text-slate-400">
          {health
            ? `${health.documents} dokumentů · ${health.chunks} chunků · ${health.chunks_with_vector} s vektorem`
            : backendError
              ? 'API nedostupné'
              : ''}
        </p>
      </header>

      <div className="inline-flex rounded-lg border border-slate-300 bg-white p-1 shadow-sm" role="tablist">
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
                'flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition',
                active ? 'bg-slate-900 text-white shadow' : 'text-slate-600 hover:bg-slate-100',
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
              <span className={clsx('text-xs', active ? 'text-slate-300' : 'text-slate-400')}>{item.hint}</span>
            </button>
          )
        })}
      </div>

      {backendError && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          Nepodařilo se načíst číselníky filtrů: {backendError}. Běží API na portu 8010?
        </div>
      )}

      {tab === 'search' ? (
        <SearchBar query={query} loading={state.status === 'loading'} onChange={setQuery} onSubmit={submit} />
      ) : (
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

      <div className="flex flex-wrap items-start justify-between gap-3">
        {tab === 'search' ? <ModeSwitch view={view} onChange={setView} /> : <p className="max-w-3xl text-sm text-slate-600">{MODE_INFO.rerank.explain}</p>}
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {tab === 'search' && view === 'compare' && (
            <label
              className="flex cursor-pointer items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-slate-700"
              title="Přidá sloupec, ve kterém Gemini ohodnotí 40 kandidátů. Stojí jedno až dvě volání API na dotaz."
            >
              <input type="checkbox" checked={rerank} onChange={(event) => setRerank(event.target.checked)} className="h-4 w-4" />
              + reranking
              <span className="text-xs text-slate-400">Gemini</span>
            </label>
          )}
          {tab === 'search' && (
            <label className="flex items-center gap-1 text-slate-600">
              výsledků
              <select
                value={limit}
                onChange={(event) => setLimit(Number(event.target.value))}
                className="rounded-md border border-slate-300 bg-white px-2 py-1"
              >
                {[3, 5, 10, 20].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          )}
          {tab === 'ask' && (
            <>
              <label className="flex items-center gap-1 text-slate-600" title="Nejvýš tolik úryvků půjde modelu jako podklad.">
                zdrojů
                <select
                  value={maxSources}
                  onChange={(event) => setMaxSources(Number(event.target.value))}
                  className="rounded-md border border-slate-300 bg-white px-2 py-1"
                >
                  {[4, 6, 8, 12].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-1 text-slate-600" title="Známka od rerankeru, pod kterou se úryvek do odpovědi nedostane.">
                známka aspoň
                <select
                  value={minGrade}
                  onChange={(event) => setMinGrade(Number(event.target.value))}
                  className="rounded-md border border-slate-300 bg-white px-2 py-1"
                >
                  {[1, 2, 3].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
              <label
                className="flex cursor-pointer items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-slate-700"
                title="Přidá sousední úryvek tam, kde je sekce rozdělená do víc oken."
              >
                <input
                  type="checkbox"
                  checked={neighbours}
                  onChange={(event) => setNeighbours(event.target.checked)}
                  className="h-4 w-4"
                />
                sousedé
              </label>
              <label
                className="flex cursor-pointer items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-slate-700"
                title="Stejná otázka se jinak vrátí z cache. Zaškrtnutím se odpověď spočítá znovu a zaplatí."
              >
                <input type="checkbox" checked={fresh} onChange={(event) => setFresh(event.target.checked)} className="h-4 w-4" />
                nová odpověď
              </label>
            </>
          )}
          <button
            type="button"
            onClick={() => setFiltersOpen((value) => !value)}
            className="flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-slate-700 hover:border-blue-400"
          >
            <SlidersHorizontal className="h-4 w-4" />
            {tab === 'search' ? 'Upřesnit hledání' : 'Omezit podklady'}
            {activeFilters > 0 && <span className="rounded-full bg-blue-600 px-1.5 text-xs text-white">{activeFilters}</span>}
          </button>
        </div>
      </div>

      {filtersOpen && <FilterPanel facets={facets} state={filters} onChange={setFilters} />}
      <ActiveFilters state={filters} facets={facets} onChange={setFilters} />

      {tab === 'ask' && (
        <AskView state={answerState} expertOpen={expertOpen} onExpert={setExpertOpen} />
      )}

      {tab === 'search' && (
        <>
          {state.status === 'error' && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
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
    </div>
  )
}
