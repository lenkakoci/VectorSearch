import type {
  AnswerRequest,
  AnswerResponse,
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

export interface StreamEvent {
  event: string
  data: Record<string, unknown>
}

/**
 * Read a server-sent event stream as it arrives.
 *
 * An answer takes ten to thirty seconds and the server reports each step it
 * reaches, so the page can say what is happening instead of spinning. Frames
 * are split on the blank line SSE puts between them; a partial frame stays in
 * the buffer until the rest of it arrives.
 */
async function* stream(path: string, body: unknown): AsyncGenerator<StreamEvent> {
  const response = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok || !response.body) {
    throw new Error(`${response.status}: ${response.statusText || 'server neposlal průběh'}`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let border = buffer.indexOf('\n\n')
    while (border >= 0) {
      const frame = buffer.slice(0, border)
      buffer = buffer.slice(border + 2)
      const event = frame.match(/^event: (.*)$/m)?.[1] ?? 'message'
      const data = frame.match(/^data: (.*)$/m)?.[1] ?? '{}'
      try {
        yield { event, data: JSON.parse(data) as Record<string, unknown> }
      } catch {
        // A frame that is not JSON says nothing useful; the next one might.
      }
      border = buffer.indexOf('\n\n')
    }
  }
}

export const api = {
  health: () => request<Health>('/health'),
  facets: () => request<Facets>('/facets'),
  search: (body: SearchRequest) => post<SearchResponse>('/search', body),
  compare: (body: CompareRequest) => post<CompareResponse>('/compare', body),
  answer: (body: AnswerRequest) => post<AnswerResponse>('/answer', body),
  answerStream: (body: AnswerRequest) => stream('/answer/stream', body),
  context: (documentId: string, chunkIndex: number, before = 1, after = 1) =>
    request<ContextResponse>(`/chunks/${documentId}/${chunkIndex}/context?before=${before}&after=${after}`),
  document: (documentId: string) => request<DocumentDetail>(`/documents/${documentId}`),
  // Not fetched but linked: the browser's own viewer opens the page in #page.
  pdfUrl: (documentId: string, page?: number | null) =>
    `${BASE}/documents/${documentId}/pdf` + (page ? `#page=${page}` : ''),
}
