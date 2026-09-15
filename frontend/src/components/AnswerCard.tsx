import clsx from 'clsx'
import { AlertTriangle, Check, HelpCircle, Scale } from 'lucide-react'
import { ANSWER_STATUS, CHECK_INFO } from '../lib/answers'
import type { AnswerResponse, CheckedStatement } from '../types'

interface Props {
  answer: AnswerResponse
  active: number | null
  onCite: (statement: CheckedStatement, sourceId: number) => void
}

// Every sentence carries the ids it cites. The chip is the way back to the
// evidence: it scrolls to the source and highlights the quote the server
// verified there.
function Citations({ statement, active, onCite }: { statement: CheckedStatement; active: number | null; onCite: Props['onCite'] }) {
  return (
    <>
      {statement.source_ids.map((id) => (
        <button
          key={id}
          type="button"
          onClick={() => onCite(statement, id)}
          title="Ukázat zdroj a zvýraznit v něm citát"
          className={clsx(
            'mx-0.5 inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded px-1 align-baseline text-xs font-semibold transition',
            active === id ? 'bg-blue-600 text-white' : 'bg-blue-100 text-blue-800 hover:bg-blue-200',
          )}
        >
          {id}
        </button>
      ))}
    </>
  )
}

export function AnswerCard({ answer, active, onCite }: Props) {
  const status = ANSWER_STATUS[answer.status]
  const validation = answer.trace.validation
  const gate = answer.trace.gate

  return (
    <section className={clsx('rounded-lg border p-4 shadow-sm', status.panel)}>
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className={clsx('rounded-full px-3 py-0.5 text-sm font-semibold', status.badge)}>{status.label}</span>
        <p className="text-sm text-slate-600">{status.explain}</p>
      </header>

      {answer.statements.length > 0 && (
        <ol className="mt-3 space-y-2">
          {answer.statements.map((statement, index) => {
            const flagged = statement.check !== 'verified'
            return (
              <li
                key={index}
                className={clsx(
                  'rounded border-l-4 bg-white/70 py-1.5 pl-3 pr-2 text-slate-800',
                  flagged ? 'border-amber-400' : 'border-green-500',
                )}
              >
                <p className={clsx('leading-relaxed', flagged && 'underline decoration-amber-500 decoration-wavy underline-offset-4')}>
                  {statement.text} <Citations statement={statement} active={active} onCite={onCite} />
                </p>
                {flagged && (
                  <p className="mt-1 flex items-start gap-1 text-xs text-amber-800">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>
                      Neověřeno – {CHECK_INFO[statement.check]}
                      {statement.note && <span className="text-amber-700"> ({statement.note})</span>}
                    </span>
                  </p>
                )}
              </li>
            )
          })}
        </ol>
      )}

      {answer.missing.length > 0 && (
        <div className="mt-3 rounded border border-slate-200 bg-white/70 p-3">
          <h3 className="flex items-center gap-1 text-sm font-semibold text-slate-700">
            <HelpCircle className="h-4 w-4 text-slate-400" />
            Ve zdrojích chybí
          </h3>
          <ul className="mt-1 list-inside list-disc text-sm text-slate-600">
            {answer.missing.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {answer.conflicts.length > 0 && (
        <div className="mt-3 rounded border border-amber-200 bg-white/70 p-3">
          <h3 className="flex items-center gap-1 text-sm font-semibold text-amber-800">
            <Scale className="h-4 w-4" />
            Rozpory mezi zdroji
          </h3>
          <ul className="mt-1 space-y-1 text-sm text-slate-700">
            {answer.conflicts.map((conflict, index) => (
              <li key={index}>
                <span className="font-medium">{conflict.topic}:</span> {conflict.description}
                {conflict.source_ids.length > 0 && (
                  <span className="ml-1 text-xs text-slate-500">zdroje {conflict.source_ids.join(', ')}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <footer className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
        {validation && (
          <span className="inline-flex items-center gap-1">
            <Check className="h-3.5 w-3.5 text-green-600" />
            ověřeno {validation.verified} z {validation.statements} vět
          </span>
        )}
        {gate && (
          <span>
            branou prošlo {gate.passed} z {gate.candidates} kandidátů (známka aspoň {gate.min_grade})
          </span>
        )}
        <span>
          model {answer.model} · prompt v{answer.prompt_version}
        </span>
        {answer.trace.total_ms != null && <span>{(answer.trace.total_ms / 1000).toFixed(1)} s</span>}
      </footer>
    </section>
  )
}
