import clsx from 'clsx'
import { Columns3, Combine, ListChecks, Sparkles, Type } from 'lucide-react'
import { MODE_INFO } from '../lib/modes'
import type { View } from '../types'

const ICONS = { fts: Type, vector: Sparkles, hybrid: Combine, rerank: ListChecks, compare: Columns3 }
const ORDER: View[] = ['fts', 'vector', 'hybrid', 'rerank', 'compare']

interface Props {
  view: View
  onChange: (view: View) => void
}

export function ModeSwitch({ view, onChange }: Props) {
  return (
    <div className="space-y-2">
      <div className="inline-flex flex-wrap rounded-lg border border-slate-300 bg-white p-1 shadow-sm" role="radiogroup">
        {ORDER.map((candidate) => {
          const Icon = ICONS[candidate]
          const active = candidate === view
          return (
            <button
              key={candidate}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange(candidate)}
              className={clsx(
                'flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition',
                active ? 'bg-blue-600 text-white shadow' : 'text-slate-600 hover:bg-slate-100',
                candidate === 'compare' && !active && 'border-l border-slate-200',
              )}
            >
              <Icon className="h-4 w-4" />
              {MODE_INFO[candidate].label}
              <span className={clsx('text-xs', active ? 'text-blue-100' : 'text-slate-400')}>
                {MODE_INFO[candidate].short}
              </span>
            </button>
          )
        })}
      </div>
      <p className="max-w-3xl text-sm text-slate-600">{MODE_INFO[view].explain}</p>
    </div>
  )
}
