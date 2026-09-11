import { X } from 'lucide-react'
import { chips, type FilterState } from '../lib/filters'
import type { Facets } from '../types'

interface Props {
  state: FilterState
  facets: Facets | null
  onChange: (state: FilterState) => void
}

export function ActiveFilters({ state, facets, onChange }: Props) {
  const items = chips(state, facets)
  if (items.length === 0) return null

  const remove = (key: (typeof items)[number]['key'], value?: string) => {
    if (key === 'years') onChange({ ...state, yearFrom: '', yearTo: '' })
    else if (key === 'content_kind') onChange({ ...state, contentKind: null })
    else onChange({ ...state, lists: { ...state.lists, [key]: state.lists[key].filter((item) => item !== value) } })
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-slate-500">Aktivní filtry:</span>
      {items.map((chip) => (
        <span
          key={`${chip.key}:${chip.value ?? ''}`}
          className="inline-flex max-w-xs items-center gap-1 rounded-full bg-blue-50 px-3 py-1 text-blue-800 ring-1 ring-blue-200"
        >
          <span className="truncate" title={chip.label}>
            {chip.label}
          </span>
          <button type="button" onClick={() => remove(chip.key, chip.value)} aria-label="odebrat filtr" className="hover:text-blue-950">
            <X className="h-3.5 w-3.5" />
          </button>
        </span>
      ))}
    </div>
  )
}
