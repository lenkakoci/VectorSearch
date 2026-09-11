// Render smoke test: the components are rendered to a string with a response
// captured from the real API (src/test/fixtures/compare.json), so a runtime
// error in the rendering tree fails here rather than in front of the audience.
// Effects (context and document fetches) do not run in server rendering and
// are covered by the API tests instead.

import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { CompareView } from '../components/CompareView'
import { DebugPanel } from '../components/DebugPanel'
import { FilterPanel } from '../components/FilterPanel'
import { ResultList } from '../components/ResultList'
import { emptyFilters, toRequestFilters } from '../lib/filters'
import type { CompareResponse, Facets } from '../types'
import compare from './fixtures/compare.json'

const data = compare as CompareResponse

describe('rendering the captured response', () => {
  it('shows the three columns with the highlighted words', () => {
    const html = renderToString(<CompareView data={data} filters={{}} />)
    expect(html).toContain('Fulltext')
    expect(html).toContain('Sémantické')
    expect(html).toContain('Hybridní')
    expect(html).toContain('<mark>')
    expect(html).not.toContain('&lt;mark&gt;')
  })

  it('renders a single ranking with scores and section paths', () => {
    const html = renderToString(<ResultList response={data.hybrid} />)
    expect(html).toContain('chunk #')
    expect(html).toContain('Proč nalezeno')
  })

  it('renders an empty ranking with its explanation', () => {
    const html = renderToString(
      <ResultList response={{ ...data.fts, hits: [] }} emptyReason="Žádný chunk neobsahuje všechna hledaná slova." />,
    )
    expect(html).toContain('žádný výsledek')
    expect(html).toContain('všechna hledaná slova')
  })

  it('renders the debug panel with lexemes and the request', () => {
    const html = renderToString(
      <DebugPanel
        state={{ status: 'ok', view: 'compare', compare: data, request: { query: data.query, limit: 3, filters: {} } }}
        open
        onToggle={() => undefined}
      />,
    )
    expect(html).toContain('tsquery czech')
    expect(html).toContain(data.query)
  })

  it('renders the filter panel from facets', () => {
    const facets: Facets = {
      author: [{ value: 'RNDr. Miroslav Bičík', count: 4 }],
      organization: [],
      municipality: [{ value: 'Lednice', count: 1 }],
      client: [],
      report_type: [],
      years: { min: 2016, max: 2025 },
      content_kinds: [
        { value: 'annex', count: 1015, with_vector: 0 },
        { value: 'prose', count: 1025, with_vector: 1025 },
      ],
      documents: [],
    }
    const html = renderToString(<FilterPanel facets={facets} state={emptyFilters()} onChange={() => undefined} />)
    expect(html).toContain('Upřesnit hledání')
    expect(html).toContain('přílohy')
  })
})

describe('filter state', () => {
  it('sends only enabled, non-empty filters', () => {
    const state = emptyFilters()
    state.lists.authors = ['Poul']
    state.lists.municipalities = ['Lednice']
    state.enabled.municipalities = false
    state.yearFrom = 2019
    state.contentKind = 'annex'
    expect(toRequestFilters(state)).toEqual({ authors: ['Poul'], date_from: '2019', content_kind: 'annex' })
  })
})
