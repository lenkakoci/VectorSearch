import clsx from 'clsx'
import { COST_INFO, PHASES, stepsOfPhase, type PhaseId, type Step } from '../lib/architecture'

interface Props {
  activeId: string | null
  onSelect: (id: string) => void
}

// One box per step, grouped by phase, with the two retrieval branches drawn side
// by side and merged under one RRF box. Colour carries the cost of the step —
// the point people ask about first is what is free and what they pay for.
export function PipelineMap({ activeId, onSelect }: Props) {
  return (
    <div className="space-y-3">
      <Legend />
      {PHASES.map((phase) => (
        <PhaseBlock key={phase.id} phaseId={phase.id} activeId={activeId} onSelect={onSelect} />
      ))}
    </div>
  )
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
      <span className="font-medium text-slate-500">Barva boxíku:</span>
      {(Object.keys(COST_INFO) as (keyof typeof COST_INFO)[]).map((cost) => (
        <span key={cost} className="flex items-center gap-1.5">
          <span className={clsx('h-2.5 w-2.5 rounded-full', COST_INFO[cost].swatch)} />
          {COST_INFO[cost].label}
        </span>
      ))}
      <span className="ml-auto text-slate-400">🛡 = bezpečnostní opatření</span>
    </div>
  )
}

function PhaseBlock({ phaseId, activeId, onSelect }: { phaseId: PhaseId; activeId: string | null; onSelect: (id: string) => void }) {
  const phase = PHASES.find((item) => item.id === phaseId)
  if (!phase) return null
  const items = stepsOfPhase(phaseId)
  const fts = items.filter((item) => item.step.branch === 'fts')
  const vector = items.filter((item) => item.step.branch === 'vector')
  const plain = items.filter((item) => !item.step.branch)

  // The retrieve phase interleaves two branch steps between the plain ones;
  // render them as a fork instead of a flat list.
  const beforeFork = plain.slice(0, plain.findIndex((item) => item.step.id === 'rrf'))
  const afterFork = plain.slice(plain.findIndex((item) => item.step.id === 'rrf'))
  const hasFork = fts.length > 0 && vector.length > 0

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <header className="mb-2">
        <h3 className="text-sm font-semibold text-slate-900">
          {phase.number} · {phase.title}
        </h3>
        <p className="text-xs text-slate-500">{phase.lead}</p>
      </header>
      {hasFork ? (
        <div className="space-y-2">
          {beforeFork.map(({ step, number }) => (
            <StepBox key={step.id} step={step} number={number} active={step.id === activeId} onSelect={onSelect} />
          ))}
          <div className="grid grid-cols-1 gap-2 rounded-md border border-dashed border-slate-200 p-2 sm:grid-cols-2">
            <div className="space-y-1">
              <p className="px-1 text-[11px] font-medium uppercase tracking-wide text-blue-600">větev slov</p>
              {fts.map(({ step, number }) => (
                <StepBox key={step.id} step={step} number={number} active={step.id === activeId} onSelect={onSelect} />
              ))}
            </div>
            <div className="space-y-1">
              <p className="px-1 text-[11px] font-medium uppercase tracking-wide text-purple-600">větev významu</p>
              {vector.map(({ step, number }) => (
                <StepBox key={step.id} step={step} number={number} active={step.id === activeId} onSelect={onSelect} />
              ))}
            </div>
          </div>
          {afterFork.map(({ step, number }) => (
            <StepBox key={step.id} step={step} number={number} active={step.id === activeId} onSelect={onSelect} />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {items.map(({ step, number }) => (
            <StepBox key={step.id} step={step} number={number} active={step.id === activeId} onSelect={onSelect} />
          ))}
        </div>
      )}
    </section>
  )
}

function StepBox({
  step,
  number,
  active,
  onSelect,
}: {
  step: Step
  number: number
  active: boolean
  onSelect: (id: string) => void
}) {
  const cost = COST_INFO[step.cost]
  const guarded = (step.safeguard?.length ?? 0) > 0
  return (
    <button
      type="button"
      onClick={() => onSelect(step.id)}
      className={clsx(
        'flex w-full flex-col items-start gap-0.5 rounded-md border px-2.5 py-2 text-left text-xs transition',
        active ? 'border-slate-900 bg-slate-900 text-white shadow' : 'border-slate-200 bg-slate-50 hover:border-blue-400 hover:bg-white',
      )}
    >
      <span className="flex w-full items-center gap-1.5">
        <span className={clsx('h-2 w-2 shrink-0 rounded-full', cost.swatch)} />
        <span className={clsx('shrink-0 font-mono', active ? 'text-slate-300' : 'text-slate-400')}>{number}</span>
        <span className="truncate font-medium">{step.title}</span>
        {guarded && <span title="Bezpečnostní opatření">🛡</span>}
      </span>
      {step.artifact && (
        <span className={clsx('truncate font-mono text-[10px]', active ? 'text-slate-300' : 'text-slate-400')}>→ {step.artifact}</span>
      )}
    </button>
  )
}
