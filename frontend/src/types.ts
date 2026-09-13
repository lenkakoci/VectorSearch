// Mirrors the Pydantic models in data/scripts/search_api.py.

export type Mode = 'fts' | 'vector' | 'hybrid' | 'rerank'
export type View = Mode | 'compare'
export type Branch = 'fts' | 'vector'
export type ContentKind = 'prose' | 'annex'

export interface Hit {
  chunk_id: string
  document_id: string
  chunk_index: number
  section: string | null
  content_kind: string
  page_from: number | null
  page_to: number | null
  chunk_raw: string
  snippet: string
  headline: string | null
  lexical_match: boolean
  title: string | null
  author: string | null
  organization: string | null
  municipality: string | null
  report_type: string | null
  report_date: string | null
  locality: string | null
  vector_rank: number | null
  vector_score: number | null
  fts_rank: number | null
  fts_score: number | null
  rrf_score: number | null
  candidate_rank?: number | null
  rerank_grade?: number | null
  rerank_reason?: string | null
}

export interface RerankStats {
  reranker: string
  model: string | null
  graded: number
  cached: number
  calls: number
  ms: number
  candidates: number
  min_grade: number
  passed: number
}

export interface SearchDebug {
  filters?: string
  filter_sql?: string
  filter_params?: string[]
  embedding_model?: string
  embedding_dimensions?: number
  rrf_k?: number
  fetch?: number
  embed_ms?: number
  embedding_cached?: boolean
  vector_ms?: number
  vector_candidates?: number
  fts_ms?: number
  fts_candidates?: number
  fts_any_ms?: number
  fts_any_candidates?: number
  fts_match?: 'all' | 'any'
  query_words?: string[]
  tsquery?: { czech: string | null; czech_literal: string | null; any?: string | null }
  rerank?: RerankStats
  rerank_error?: string
  [key: string]: unknown
}

export interface SearchResponse {
  query: string
  mode: Mode
  limit: number
  fetch: number
  hits: Hit[]
  debug: SearchDebug
}

export interface CompareResponse {
  query: string
  fts: SearchResponse
  vector: SearchResponse
  hybrid: SearchResponse
  rerank?: SearchResponse | null
}

export interface FacetValue {
  value: string
  count: number
}

export interface DocumentSummary {
  id: string
  title: string | null
  author: string | null
  report_date: string | null
  report_type: string | null
  locality: string | null
  municipality: string | null
  organization: string | null
  chunks: number
  chunks_with_vector: number
}

export interface Facets {
  author: FacetValue[]
  organization: FacetValue[]
  municipality: FacetValue[]
  client: FacetValue[]
  report_type: FacetValue[]
  years: { min: number | null; max: number | null }
  content_kinds: { value: string; count: number; with_vector: number }[]
  documents: DocumentSummary[]
}

export interface RequestFilters {
  authors?: string[]
  organizations?: string[]
  municipalities?: string[]
  clients?: string[]
  report_types?: string[]
  locality?: string
  date_from?: string
  date_to?: string
  document_ids?: string[]
  content_kind?: ContentKind
}

export interface CompareRequest {
  query: string
  limit: number
  filters: RequestFilters
  rerank?: boolean
}

export interface SearchRequest {
  query: string
  limit: number
  filters: RequestFilters
  mode: Mode
}

export interface ContextChunk {
  chunk_index: number
  section: string | null
  content_kind: string
  page_from: number | null
  page_to: number | null
  chunk_raw: string
  is_hit: boolean
}

export interface ContextResponse {
  document_id: string
  title: string | null
  chunks: ContextChunk[]
}

export interface DocumentDetail {
  id: string
  source_file: string
  title: string | null
  report_type: string | null
  locality: string | null
  report_date: string | null
  author: string | null
  client: string | null
  summary: string | null
  extraction: Record<string, unknown>
  extraction_model: string | null
  extraction_schema_version: number
  chunks: number
}

export interface Health {
  status: string
  documents: number
  chunks: number
  chunks_with_vector: number
}
