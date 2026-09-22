import { Loader2, MessagesSquare, Quote, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import type { AnswerState } from '../hooks/useAnswer'
import { anchorOf } from '../lib/answers'
import type { CheckedStatement } from '../types'
import { AnswerCard } from './AnswerCard'
import { AnswerProgress } from './AnswerProgress'
import { EmptyState, type EmptyStep } from './EmptyState'
import { PipelineTrace } from './PipelineTrace'
import { SourceList, type Highlighted } from './SourceList'

interface Props {
  state: AnswerState
  expertOpen: boolean
  onExpert: (open: boolean) => void
}

const ASK_STEPS: EmptyStep[] = [
  { icon: MessagesSquare, title: 'Zeptejte se celou větou', text: 'Odpověď se složí jen z úryvků, které vyhledávání najde a které dostanou známku relevance.' },
  { icon: Quote, title: 'Každá věta má zdroj', text: 'Číslo za větou je odkaz na úryvek. Kliknutím se zdroj otevře a ověřený citát v něm zvýrazní.' },
  { icon: ShieldCheck, title: 'Bez podkladů nic nevymýšlí', text: 'Když v posudcích podklad není, systém odpoví „Bez podkladů“ a model se vůbec nezavolá.' },
]

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

  if (state.status === 'idle') return <EmptyState steps={ASK_STEPS} />

  if (state.status === 'error') {
    return (
      <div className="rounded-lg border border-clay-200 bg-clay-50 p-3 text-sm text-clay-700">
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
      <div className="rounded-lg border border-slate-200 bg-white p-6 text-slate-600 shadow-sm">
        <div className="flex items-center gap-3">
          <Loader2 className="h-5 w-5 animate-spin text-brand-600" />
          <div className="text-sm">
            <p className="font-medium text-slate-700">Hledám podklady a skládám odpověď…</p>
            <p className="text-slate-500">Nejdřív 40 kandidátů dostane známku, pak z nich vzniká odpověď. Deset až třicet sekund.</p>
          </div>
        </div>
        <AnswerProgress steps={state.progress ?? []} />
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
