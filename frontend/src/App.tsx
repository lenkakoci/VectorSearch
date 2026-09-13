import { SlidersHorizontal } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { ActiveFilters } from './components/ActiveFilters'
import { CompareView } from './components/CompareView'
import { DebugPanel } from './components/DebugPanel'
import { FilterPanel } from './components/FilterPanel'
import { ModeSwitch } from './components/ModeSwitch'
import { ResultList } from './components/ResultList'
import { SearchBar } from './components/SearchBar'
import { useSearch } from './hooks/useSearch'
import { countActive, emptyFilters, toRequestFilters, type FilterState } from './lib/filters'
import { MODE_INFO } from './lib/modes'
import { api } from './services/api'
import type { Facets, Health, View } from './types'

export default function App() {
  const [query, setQuery] = useState('')
  const [view, setView] = useState<View>('compare')
  const [limit, setLimit] = useState(5)
  const [rerank, setRerank] = useState(false)
  const [filters, setFilters] = useState<FilterState>(emptyFilters)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [debugOpen, setDebugOpen] = useState(false)
  const [facets, setFacets] = useState<Facets | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [backendError, setBackendError] = useState<string | null>(null)
  const { state, run } = useSearch()
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

  // A change of mode, filter, limit or reranking re-runs the last query, so the
  // demo can flip between views without retyping. Query embeddings and grades
  // are cached server side, so this costs SQL and only the grades not seen yet.
  const first = useRef(true)
  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    if (lastQuery.current) void run(lastQuery.current, view, toRequestFilters(filters), limit, rerank)
  }, [view, filters, limit, rerank, run])

  const activeFilters = countActive(filters)
  const requestFilters = toRequestFilters(filters)

  return (
    <div className="mx-auto max-w-[96rem] space-y-4 p-4 md:p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">VectorSearch</h1>
          <p className="text-sm text-slate-500">Demo vyhledávání v geologických posudcích: slova × význam × obojí × reranking</p>
        </div>
        <p className="text-xs text-slate-400">
          {health
            ? `${health.documents} dokumentů · ${health.chunks} chunků · ${health.chunks_with_vector} s vektorem`
            : backendError
              ? 'API nedostupné'
              : ''}
        </p>
      </header>

      {backendError && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          Nepodařilo se načíst číselníky filtrů: {backendError}. Běží API na portu 8010?
        </div>
      )}

      <SearchBar query={query} loading={state.status === 'loading'} onChange={setQuery} onSubmit={submit} />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <ModeSwitch view={view} onChange={setView} />
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {view === 'compare' && (
            <label
              className="flex cursor-pointer items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-slate-700"
              title="Přidá sloupec, ve kterém Gemini ohodnotí 40 kandidátů. Stojí jedno až dvě volání API na dotaz."
            >
              <input type="checkbox" checked={rerank} onChange={(event) => setRerank(event.target.checked)} className="h-4 w-4" />
              + reranking
              <span className="text-xs text-slate-400">Gemini</span>
            </label>
          )}
          <label className="flex items-center gap-1 text-slate-600">
            výsledků
            <select value={limit} onChange={(event) => setLimit(Number(event.target.value))} className="rounded-md border border-slate-300 bg-white px-2 py-1">
              {[3, 5, 10, 20].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={() => setFiltersOpen((value) => !value)}
            className="flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-slate-700 hover:border-blue-400"
          >
            <SlidersHorizontal className="h-4 w-4" />
            Upřesnit hledání
            {activeFilters > 0 && <span className="rounded-full bg-blue-600 px-1.5 text-xs text-white">{activeFilters}</span>}
          </button>
        </div>
      </div>

      {filtersOpen && <FilterPanel facets={facets} state={filters} onChange={setFilters} />}
      <ActiveFilters state={filters} facets={facets} onChange={setFilters} />

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
    </div>
  )
}
