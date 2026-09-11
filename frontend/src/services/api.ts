import type {
  CompareRequest,
  CompareResponse,
  ContextResponse,
  DocumentDetail,
  Facets,
  Health,
  SearchRequest,
  SearchResponse,
} from '../types'

// Relative by default: Vite proxies /api in development and nginx in Docker.
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init)
  const text = await response.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      throw new Error(`${response.status}: server nevrátil JSON (${text.slice(0, 120)})`)
    }
  }
  if (!response.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail
    const message = typeof detail === 'string' ? detail : JSON.stringify(detail ?? response.statusText)
    throw new Error(`${response.status}: ${message}`)
  }
  return data as T
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export const api = {
  health: () => request<Health>('/health'),
  facets: () => request<Facets>('/facets'),
  search: (body: SearchRequest) => post<SearchResponse>('/search', body),
  compare: (body: CompareRequest) => post<CompareResponse>('/compare', body),
  context: (documentId: string, chunkIndex: number, before = 1, after = 1) =>
    request<ContextResponse>(`/chunks/${documentId}/${chunkIndex}/context?before=${before}&after=${after}`),
  document: (documentId: string) => request<DocumentDetail>(`/documents/${documentId}`),
}
