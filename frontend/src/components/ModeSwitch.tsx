import clsx from 'clsx'
import { Columns3, Combine, ListChecks, Sparkles, Type } from 'lucide-react'
import { Fragment } from 'react'
import { MODE_INFO } from '../lib/modes'
import type { View } from '../types'

const ICONS = { fts: Type, vector: Sparkles, hybrid: Combine, rerank: ListChecks, compare: Columns3 }
// Comparing is the default view and the point of the demo, so it comes first
// and stands apart from the four single modes.
const ORDER: View[] = ['compare', 'fts', 'vector', 'hybrid', 'rerank']

interface Props {
  view: View
  onChange: (view: View) => void
}

export function ModeSwitch({ view, onChange }: Props) {
  return (
    <div className="inline-flex flex-wrap items-center rounded-lg border border-slate-300 bg-white p-1 shadow-sm" role="radiogroup" aria-label="Režim hledání">
      {ORDER.map((candidate, index) => {
        const Icon = ICONS[candidate]
        const active = candidate === view
        return (
          <Fragment key={candidate}>
            {index === 1 && <span className="mx-1 h-6 w-px bg-slate-200" aria-hidden />}
            <button
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange(candidate)}
              title={MODE_INFO[candidate].short}
              className={clsx(
                'flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition',
                active ? 'bg-brand-700 text-white shadow' : 'text-slate-600 hover:bg-slate-100',
              )}
            >
              <Icon className="h-4 w-4" />
              {MODE_INFO[candidate].label}
            </button>
          </Fragment>
        )
      })}
    </div>
  )
}
