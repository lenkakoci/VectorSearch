import type { ContentKind, Facets, RequestFilters } from '../types'

export type ListKey = 'authors' | 'organizations' | 'municipalities' | 'clients' | 'report_types' | 'document_ids'
export type FilterKey = ListKey | 'years' | 'content_kind'

export interface FilterState {
  lists: Record<ListKey, string[]>
  yearFrom: number | ''
  yearTo: number | ''
  contentKind: ContentKind | null
  // A filter can be switched off without losing its selection.
  enabled: Record<FilterKey, boolean>
}

export interface ListFilterSpec {
  key: ListKey
  facet: 'author' | 'organization' | 'municipality' | 'client' | 'report_type' | 'documents'
  label: string
}

export const LIST_FILTERS: ListFilterSpec[] = [
  { key: 'authors', facet: 'author', label: 'Autor' },
  { key: 'organizations', facet: 'organization', label: 'Organizace' },
  { key: 'municipalities', facet: 'municipality', label: 'Obec' },
  { key: 'clients', facet: 'client', label: 'Klient' },
  { key: 'report_types', facet: 'report_type', label: 'Typ průzkumu' },
  { key: 'document_ids', facet: 'documents', label: 'Dokument' },
]

export const CONTENT_KIND_LABEL: Record<ContentKind, string> = {
  prose: 'tělo zprávy',
  annex: 'přílohy',
}

export function emptyFilters(): FilterState {
  return {
    lists: { authors: [], organizations: [], municipalities: [], clients: [], report_types: [], document_ids: [] },
    yearFrom: '',
    yearTo: '',
    contentKind: null,
    enabled: {
      authors: true,
      organizations: true,
      municipalities: true,
      clients: true,
      report_types: true,
      document_ids: true,
      years: true,
      content_kind: true,
    },
  }
}

export function isActive(state: FilterState, key: FilterKey): boolean {
  if (!state.enabled[key]) return false
  if (key === 'years') return state.yearFrom !== '' || state.yearTo !== ''
  if (key === 'content_kind') return state.contentKind !== null
  return state.lists[key].length > 0
}

export function countActive(state: FilterState): number {
  const keys: FilterKey[] = [...LIST_FILTERS.map((spec) => spec.key), 'years', 'content_kind']
  return keys.filter((key) => isActive(state, key)).length
}

export function toRequestFilters(state: FilterState): RequestFilters {
  const out: RequestFilters = {}
  for (const spec of LIST_FILTERS) {
    if (isActive(state, spec.key)) out[spec.key] = state.lists[spec.key]
  }
  if (isActive(state, 'years')) {
    if (state.yearFrom !== '') out.date_from = String(state.yearFrom)
    if (state.yearTo !== '') out.date_to = String(state.yearTo)
  }
  if (isActive(state, 'content_kind') && state.contentKind) out.content_kind = state.contentKind
  return out
}

export interface Chip {
  key: FilterKey
  label: string
  value?: string
}

export function chips(state: FilterState, facets: Facets | null): Chip[] {
  const out: Chip[] = []
  for (const spec of LIST_FILTERS) {
    if (!isActive(state, spec.key)) continue
    for (const value of state.lists[spec.key]) {
      const label =
        spec.key === 'document_ids'
          ? facets?.documents.find((doc) => doc.id === value)?.title ?? value
          : value
      out.push({ key: spec.key, label: `${spec.label}: ${label}`, value })
    }
  }
  if (isActive(state, 'years')) {
    out.push({ key: 'years', label: `Období: ${state.yearFrom || '…'} – ${state.yearTo || '…'}` })
  }
  if (isActive(state, 'content_kind') && state.contentKind) {
    out.push({ key: 'content_kind', label: `Část: ${CONTENT_KIND_LABEL[state.contentKind]}` })
  }
  return out
}
