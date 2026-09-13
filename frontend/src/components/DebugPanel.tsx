import { formatScore, MAX_GRADE, MODE_INFO } from '../lib/modes'
import type { SearchState } from '../hooks/useSearch'
import type { SearchResponse } from '../types'
import { modesOf, responseOf } from './CompareView'

interface Props {
  state: SearchState
  open: boolean
  onToggle: (open: boolean) => void
}

function Block({ response }: { response: SearchResponse }) {
  const debug = response.debug
  const rerank = debug.rerank
  const isRerank = response.mode === 'rerank'
  const facts: [string, unknown][] = [
    ['režim', `${response.mode} (${MODE_INFO[response.mode].label})`],
    ['limit / načteno na větev', `${response.limit} / ${response.fetch}`],
    ['RRF k', debug.rrf_k],
    ['embedding model', debug.embedding_model ? `${debug.embedding_model} · ${debug.embedding_dimensions} dim` : '–'],
    ['embedding', debug.embed_ms != null ? `${debug.embed_ms} ms${debug.embedding_cached ? ' (z cache)' : ''}` : 'neběžel'],
    ['vektorová větev', debug.vector_ms != null ? `${debug.vector_candidates} kandidátů · ${debug.vector_ms} ms` : 'neběžela'],
    ['fulltext, všechna slova', debug.fts_ms != null ? `${debug.fts_candidates} kandidátů · ${debug.fts_ms} ms` : 'neběžel'],
    ['fulltext, libovolné slovo', debug.fts_any_ms != null ? `${debug.fts_any_candidates} kandidátů · ${debug.fts_any_ms} ms` : 'neběžel'],
    ['fulltext tohoto režimu', debug.fts_match === 'any' ? 'libovolné slovo' : 'všechna slova'],
    ['tsquery czech', debug.tsquery?.czech],
    ['tsquery czech_literal', debug.tsquery?.czech_literal],
    ['tsquery libovolné slovo', debug.tsquery?.any],
    ['metadata filtry', debug.filters || '(žádné)'],
    ['filtr SQL', debug.filter_sql || '(žádný)'],
    ['filtr parametry', debug.filter_params?.length ? debug.filter_params.join(' | ') : '(žádné)'],
  ]
  if (rerank) {
    facts.push(
      ['reranker', `${rerank.reranker} · ${rerank.model ?? '–'}`],
      ['ohodnoceno', `${rerank.candidates} kandidátů: ${rerank.graded} nově, ${rerank.cached} z cache · ${rerank.calls} volání · ${rerank.ms} ms`],
      ['brána relevance', `${rerank.passed} z ${rerank.candidates} má známku aspoň ${rerank.min_grade}`],
    )
  }
  if (debug.rerank_error) facts.push(['chyba rerankingu', debug.rerank_error])

  return (
    <div className="space-y-2">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-xs">
        {facts.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-slate-500">{label}</dt>
            <dd className="font-mono text-slate-800">{value == null || value === '' ? '–' : String(value)}</dd>
          </div>
        ))}
      </dl>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-left text-slate-500">
            <tr>
              <th className="py-1 pr-2">#</th>
              <th className="py-1 pr-2">dokument</th>
              <th className="py-1 pr-2">chunk</th>
              {isRerank && <th className="py-1 pr-2">známka</th>}
              {isRerank && <th className="py-1 pr-2">kandidát</th>}
              <th className="py-1 pr-2">vektor pořadí</th>
              <th className="py-1 pr-2">kosinus</th>
              <th className="py-1 pr-2">fulltext pořadí</th>
              <th className="py-1 pr-2">fulltext skóre</th>
              <th className="py-1 pr-2">RRF</th>
              <th className="py-1 pr-2">slova v textu</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {response.hits.map((hit, index) => (
              <tr key={hit.chunk_id} className="border-t border-slate-100">
                <td className="py-1 pr-2">{index + 1}</td>
                <td className="max-w-[16rem] truncate py-1 pr-2 font-sans" title={hit.title ?? ''}>
                  {hit.title ?? '–'}
                </td>
                <td className="py-1 pr-2">#{hit.chunk_index}</td>
                {isRerank && <td className="py-1 pr-2">{hit.rerank_grade == null ? '–' : `${hit.rerank_grade}/${MAX_GRADE}`}</td>}
                {isRerank && <td className="py-1 pr-2">{hit.candidate_rank ?? '–'}</td>}
                <td className="py-1 pr-2">{hit.vector_rank ?? '–'}</td>
                <td className="py-1 pr-2">{formatScore(hit.vector_score)}</td>
                <td className="py-1 pr-2">{hit.fts_rank ?? '–'}</td>
                <td className="py-1 pr-2">{formatScore(hit.fts_score)}</td>
                <td className="py-1 pr-2">{formatScore(hit.rrf_score)}</td>
                <td className="py-1 pr-2">{hit.lexical_match ? 'ano' : 'ne'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function DebugPanel({ state, open, onToggle }: Props) {
  if (state.status !== 'ok') return null
  return (
    <details open={open} onToggle={(event) => onToggle((event.target as HTMLDetailsElement).open)} className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <summary className="cursor-pointer select-none px-4 py-2 text-sm font-semibold text-slate-700">
        Expert / debug
        <span className="ml-2 text-xs font-normal text-slate-400">
          {state.ms != null && `celkem ${Math.round(state.ms)} ms`}
        </span>
      </summary>
      <div className="space-y-4 border-t border-slate-100 px-4 py-3">
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Požadavek</h3>
          <pre className="overflow-x-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(state.request, null, 2)}</pre>
        </div>
        {state.single && <Block response={state.single} />}
        {state.compare &&
          modesOf(state.compare).map((mode) => (
            <div key={mode}>
              <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">{MODE_INFO[mode].label}</h3>
              <Block response={responseOf(state.compare!, mode)} />
            </div>
          ))}
      </div>
    </details>
  )
}
