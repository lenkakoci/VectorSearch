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
  // Grades that came from the cache on disk, so they survived the process.
  from_disk?: number
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

// --- Answers -----------------------------------------------------------------
// Mirrors AnswerResponse in data/scripts/search_api.py. `no_evidence` never
// comes from the model: it is what the server returns when no candidate
// reached the relevance gate and nothing was generated at all.

export type AnswerStatus = 'answered' | 'partial' | 'insufficient' | 'no_evidence'

export type CheckResult = 'verified' | 'invalid_source' | 'unsupported' | 'quote_not_found' | 'number_unsupported'

export interface CheckedStatement {
  text: string
  source_ids: number[]
  quotes: string[]
  check: CheckResult
  note: string
}

export interface AnswerConflict {
  topic: string
  source_ids: number[]
  description: string
}

export interface AnswerSource {
  id: number
  role: string
  cited: boolean
  chunk_id: string
  document_id: string
  chunk_index: number
  section: string | null
  content_kind: string
  page_from: number | null
  page_to: number | null
  chunk_raw: string
  title: string | null
  municipality: string | null
  report_type: string | null
  report_date: string | null
  organization: string | null
  token_count: number | null
  rerank_grade: number | null
  rerank_reason: string | null
  candidate_rank: number | null
}

export interface GateTrace {
  min_grade: number
  candidates: number
  passed: number
}

export interface ContextTrace {
  candidates: number
  eligible: number
  chosen: number
  documents: number
  tokens: number
  dropped_below_gate: number
  dropped_over_budget: number
  dropped_per_document: number
  neighbours: number
  sources: number
}

export interface GenerationTrace {
  model: string
  prompt_version: number
  ms: number
  model_status: string
}

export interface ValidationTrace {
  statements: number
  verified: number
  flagged: number
  checks: Record<CheckResult, number>
  cited_sources: number[]
}

export interface AnswerTrace {
  retrieval?: SearchDebug
  rerank?: RerankStats | null
  gate?: GateTrace
  context?: ContextTrace
  generation?: GenerationTrace
  validation?: ValidationTrace
  total_ms?: number
  // "hit" when the answer came from the cache and no model was called.
  cache?: string
  prompt?: string
  raw_answer?: unknown
  [key: string]: unknown
}

export interface AnswerOptions {
  candidates?: number
  min_grade?: number
  max_sources?: number
  per_document?: number
  token_budget?: number
  neighbours?: boolean
  trace?: boolean
  fresh?: boolean
}

export interface AnswerRequest {
  question: string
  filters: RequestFilters
  options?: AnswerOptions
}

export interface AnswerResponse {
  question: string
  status: AnswerStatus
  statements: CheckedStatement[]
  missing: string[]
  conflicts: AnswerConflict[]
  sources: AnswerSource[]
  model: string
  prompt_version: number
  trace: AnswerTrace
}
