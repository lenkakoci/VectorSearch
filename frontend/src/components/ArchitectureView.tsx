import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { DETAILS, COST_INFO, detailOf, TOPICS } from '../lib/architecture'
import { PipelineMap } from './PipelineMap'
import { StepDetail } from './StepDetail'

const OVERVIEW = ['PDF', 'struktura', 'PostgreSQL', 'kandidáti', 'reranking', 'odpověď']

// The whole tab is one controlled selection: clicking a box in the diagram or a
// topic card below it sets `activeId`, and the panel on the right renders
// whichever detail matches. No API call anywhere in this component — it has to
// work with the backend switched off, mid-demo.
export function ArchitectureView() {
  const [activeId, setActiveId] = useState<string | null>(null)
  const [expandAll, setExpandAll] = useState(false)
  const detail = activeId ? (detailOf(activeId) ?? null) : null

  // Arrow keys step through the pipeline in order, Esc closes the panel —
  // useful when someone is presenting and does not want to keep reaching
  // for the mouse between boxes.
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setActiveId(null)
        return
      }
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
      const target = event.target as HTMLElement | null
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
      event.preventDefault()
      const index = activeId ? DETAILS.findIndex((item) => item.id === activeId) : -1
      const step = event.key === 'ArrowDown' ? 1 : -1
      const nextIndex = index === -1 ? 0 : (index + step + DETAILS.length) % DETAILS.length
      setActiveId(DETAILS[nextIndex].id)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [activeId])

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
        <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-slate-500">
            Zpracování posudku běží jednou, offline. Hledání a odpověď běží při každém dotazu. Klikněte na kterýkoli krok níže, nebo
            listujte šipkami.
          </p>
          <button
            type="button"
            onClick={() => setExpandAll((value) => !value)}
            className="shrink-0 rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-600 hover:border-blue-400"
          >
            {expandAll ? 'Skrýt podrobnosti' : 'Rozbalit vše (pro tisk)'}
          </button>
        </div>
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

      {expandAll && (
        <section className="space-y-3">
          <h3 className="text-sm font-semibold text-slate-900">Všechny kroky a témata — plný text</h3>
          {DETAILS.map((item) => (
            <StepDetail key={item.id} detail={item} onClose={() => setExpandAll(false)} />
          ))}
        </section>
      )}
    </div>
  )
}
