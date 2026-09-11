import clsx from 'clsx'
import { CONTENT_KIND_LABEL, LIST_FILTERS, emptyFilters, type FilterKey, type FilterState } from '../lib/filters'
import type { ContentKind, Facets } from '../types'
import { MultiSelect, type Option } from './MultiSelect'

interface Props {
  facets: Facets | null
  state: FilterState
  onChange: (state: FilterState) => void
}

function Toggle({ on, onChange, label }: { on: boolean; onChange: (on: boolean) => void; label: string }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-slate-700">
      <span
        role="switch"
        aria-checked={on}
        onClick={() => onChange(!on)}
        className={clsx(
          'relative inline-block h-5 w-9 rounded-full transition',
          on ? 'bg-blue-600' : 'bg-slate-300',
        )}
      >
        <span
          className={clsx(
            'absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition',
            on ? 'left-4' : 'left-0.5',
          )}
        />
      </span>
      {label}
    </label>
  )
}

export function FilterPanel({ facets, state, onChange }: Props) {
  const setEnabled = (key: FilterKey, on: boolean) => onChange({ ...state, enabled: { ...state.enabled, [key]: on } })

  const optionsFor = (facet: (typeof LIST_FILTERS)[number]['facet']): Option[] => {
    if (!facets) return []
    if (facet === 'documents') {
      return facets.documents.map((doc) => ({
        value: doc.id,
        label: `${doc.title ?? '(bez názvu)'}${doc.report_date ? ` (${doc.report_date.slice(0, 4)})` : ''}`,
        count: doc.chunks,
      }))
    }
    return facets[facet].map((item) => ({ value: item.value, count: item.count }))
  }

  const kindCount = (kind: ContentKind) => facets?.content_kinds.find((item) => item.value === kind)?.count

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold text-slate-700">Upřesnit hledání</h2>
        <button type="button" onClick={() => onChange(emptyFilters())} className="text-sm text-blue-600 hover:underline">
          Vymazat filtry
        </button>
      </div>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {LIST_FILTERS.map((spec) => (
          <div key={spec.key} className="space-y-1.5">
            <Toggle on={state.enabled[spec.key]} onChange={(on) => setEnabled(spec.key, on)} label={spec.label} />
            <MultiSelect
              options={optionsFor(spec.facet)}
              selected={state.lists[spec.key]}
              disabled={!state.enabled[spec.key]}
              onChange={(selected) =>
                onChange({
                  ...state,
                  lists: { ...state.lists, [spec.key]: selected },
                  enabled: { ...state.enabled, [spec.key]: true },
                })
              }
            />
          </div>
        ))}

        <div className="space-y-1.5">
          <Toggle on={state.enabled.years} onChange={(on) => setEnabled('years', on)} label="Období (rok zprávy)" />
          <div className="flex items-center gap-2 text-sm">
            <input
              type="number"
              placeholder={facets?.years.min != null ? String(facets.years.min) : 'od'}
              min={facets?.years.min ?? undefined}
              max={facets?.years.max ?? undefined}
              value={state.yearFrom}
              disabled={!state.enabled.years}
              onChange={(event) =>
                onChange({
                  ...state,
                  yearFrom: event.target.value === '' ? '' : Number(event.target.value),
                  enabled: { ...state.enabled, years: true },
                })
              }
              className="w-24 rounded-md border border-slate-300 px-2 py-1.5 disabled:bg-slate-50 disabled:text-slate-400"
            />
            <span className="text-slate-400">–</span>
            <input
              type="number"
              placeholder={facets?.years.max != null ? String(facets.years.max) : 'do'}
              min={facets?.years.min ?? undefined}
              max={facets?.years.max ?? undefined}
              value={state.yearTo}
              disabled={!state.enabled.years}
              onChange={(event) =>
                onChange({
                  ...state,
                  yearTo: event.target.value === '' ? '' : Number(event.target.value),
                  enabled: { ...state.enabled, years: true },
                })
              }
              className="w-24 rounded-md border border-slate-300 px-2 py-1.5 disabled:bg-slate-50 disabled:text-slate-400"
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <Toggle on={state.enabled.content_kind} onChange={(on) => setEnabled('content_kind', on)} label="Část zprávy" />
          <div className="flex flex-wrap gap-3 text-sm">
            {([null, 'prose', 'annex'] as (ContentKind | null)[]).map((kind) => (
              <label key={kind ?? 'all'} className="flex cursor-pointer items-center gap-1.5">
                <input
                  type="radio"
                  name="content_kind"
                  checked={state.contentKind === kind}
                  disabled={!state.enabled.content_kind}
                  onChange={() => onChange({ ...state, contentKind: kind, enabled: { ...state.enabled, content_kind: true } })}
                />
                {kind ? CONTENT_KIND_LABEL[kind] : 'vše'}
                {kind && kindCount(kind) != null && <span className="text-xs text-slate-400">{kindCount(kind)}</span>}
              </label>
            ))}
          </div>
          <p className="text-xs text-slate-400">Přílohy (vrtné protokoly, formuláře) nemají vektor – najde je jen fulltext.</p>
        </div>
      </div>
    </div>
  )
}
