import clsx from 'clsx'
import { useState } from 'react'
import { COST_INFO, detailOf, TOPICS } from '../lib/architecture'
import { PipelineMap } from './PipelineMap'
import { StepDetail } from './StepDetail'

const OVERVIEW = ['PDF', 'struktura', 'PostgreSQL', 'kandidáti', 'reranking', 'odpověď']

// The whole tab is one controlled selection: clicking a box in the diagram or a
// topic card below it sets `activeId`, and the panel on the right renders
// whichever detail matches. No API call anywhere in this component — it has to
// work with the backend switched off, mid-demo.
export function ArchitectureView() {
  const [activeId, setActiveId] = useState<string | null>(null)
  const detail = activeId ? (detailOf(activeId) ?? null) : null

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
        <p className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
          {OVERVIEW.map((item, index) => (
            <span key={item} className="flex items-center gap-2">
              {index > 0 && <span className="text-slate-300">→</span>}
              <span className="font-medium">{item}</span>
            </span>
          ))}
        </p>
        <p className="mt-1 text-xs text-slate-500">
          Zpracování posudku běží jednou, offline. Hledání a odpověď běží při každém dotazu. Klikněte na kterýkoli krok níže.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_26rem]">
        <PipelineMap activeId={activeId} onSelect={setActiveId} />
        <StepDetail detail={detail} onClose={() => setActiveId(null)} />
      </div>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-slate-900">Témata napříč pipeline</h3>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {TOPICS.map((topic) => (
            <button
              key={topic.id}
              type="button"
              onClick={() => setActiveId(topic.id)}
              className={clsx(
                'rounded-lg border p-3 text-left text-xs transition',
                activeId === topic.id ? 'border-slate-900 bg-slate-900 text-white shadow' : 'border-slate-200 bg-white hover:border-blue-400',
              )}
            >
              <span
                className={clsx(
                  'mb-1 inline-block rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide',
                  activeId === topic.id ? 'bg-white/15 text-white' : 'bg-slate-100 text-slate-500',
                )}
              >
                {topic.tag}
              </span>
              <p className="font-medium">{topic.title}</p>
              <p className={clsx('mt-0.5', activeId === topic.id ? 'text-slate-300' : 'text-slate-500')}>{topic.lead}</p>
            </button>
          ))}
        </div>
      </section>

      <p className="text-xs text-slate-400">
        Barvy shrnují cenu kroku: {COST_INFO.local.label}, {COST_INFO.sql.label}, {COST_INFO.paid.label}.
      </p>
    </div>
  )
}
