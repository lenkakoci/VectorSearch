import { useCallback, useRef, useState } from 'react'
import { api } from '../services/api'
import type { CompareRequest, CompareResponse, RequestFilters, SearchRequest, SearchResponse, View } from '../types'

export interface SearchState {
  status: 'idle' | 'loading' | 'ok' | 'error'
  view?: View
  request?: SearchRequest | CompareRequest
  single?: SearchResponse
  compare?: CompareResponse
  error?: string
  ms?: number
}

export function useSearch() {
  const [state, setState] = useState<SearchState>({ status: 'idle' })
  const counter = useRef(0)

  const run = useCallback(
    async (query: string, view: View, filters: RequestFilters, limit: number, rerank = false) => {
      const id = ++counter.current
      const started = performance.now()
      setState((previous) => ({ ...previous, status: 'loading', error: undefined }))
      try {
        if (view === 'compare') {
          const request: CompareRequest = { query, limit, filters, rerank }
          const compare = await api.compare(request)
          if (id !== counter.current) return
          setState({ status: 'ok', view, request, compare, ms: performance.now() - started })
        } else {
          const request: SearchRequest = { query, mode: view, limit, filters }
          const single = await api.search(request)
          if (id !== counter.current) return
          setState({ status: 'ok', view, request, single, ms: performance.now() - started })
        }
      } catch (error) {
        if (id !== counter.current) return
        setState((previous) => ({ ...previous, status: 'error', error: (error as Error).message }))
      }
    },
    [],
  )

  return { state, run }
}
