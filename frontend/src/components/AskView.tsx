import { Loader2 } from 'lucide-react'
import { useState } from 'react'
import type { AnswerState } from '../hooks/useAnswer'
import { anchorOf } from '../lib/answers'
import type { CheckedStatement } from '../types'
import { AnswerCard } from './AnswerCard'
import { PipelineTrace } from './PipelineTrace'
import { SourceList, type Highlighted } from './SourceList'

interface Props {
  state: AnswerState
  expertOpen: boolean
  onExpert: (open: boolean) => void
}

export function AskView({ state, expertOpen, onExpert }: Props) {
  const [highlight, setHighlight] = useState<Highlighted | null>(null)

  const cite = (statement: CheckedStatement, sourceId: number) => {
    setHighlight({ id: sourceId, quotes: statement.quotes })
    if (typeof window !== 'undefined') {
      window.requestAnimationFrame(() =>
        document.getElementById(anchorOf(sourceId))?.scrollIntoView({ behavior: 'smooth', block: 'center' }),
      )
    }
  }

  if (state.status === 'idle') {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-slate-500">
        Zeptejte se celou větou. Odpověď se složí jen z nalezených úryvků a u každé věty bude zdroj.
        <br />
        Když v posudcích podklad není, systém to řekne a nic si nevymyslí.
      </div>
    )
  }

  if (state.status === 'error') {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {state.error}
        {state.error?.startsWith('503') && <span className="ml-1">Generování je dočasně nedostupné, vyhledávání funguje dál.</span>}
        {(state.error?.startsWith('504') || state.error?.startsWith('502')) && (
          <span className="ml-1">Odpověď se nestihla vrátit včas. Model bývá pomalý nárazově, zkuste otázku poslat znovu.</span>
        )}
      </div>
    )
  }

  if (state.status === 'loading') {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white p-6 text-slate-600 shadow-sm">
        <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
        <div className="text-sm">
          <p className="font-medium text-slate-700">Hledám podklady a skládám odpověď…</p>
          <p className="text-slate-500">Nejdřív 40 kandidátů dostane známku, pak z nich vzniká odpověď. Deset až třicet sekund.</p>
        </div>
      </div>
    )
  }

  const answer = state.answer!
  const noEvidence = answer.status === 'no_evidence'

  return (
    <div className="space-y-4">
      <AnswerCard answer={answer} active={highlight?.id ?? null} onCite={cite} />
      <SourceList
        sources={answer.sources}
        highlight={highlight}
        title={noEvidence ? 'Nejbližší nalezené úryvky' : 'Zdroje'}
        note={
          noEvidence
            ? 'Žádný nedosáhl na bránu relevance, do odpovědi by nešly. Posuďte sami.'
            : undefined
        }
      />
      <PipelineTrace answer={answer} request={state.request} ms={state.ms} open={expertOpen} onToggle={onExpert} />
    </div>
  )
}
