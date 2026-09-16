import clsx from 'clsx'
import { Check, Loader2 } from 'lucide-react'
import type { ProgressStep } from '../hooks/useAnswer'

interface Props {
  steps: ProgressStep[]
}

// What each step of the chain looks like while it is happening. The numbers
// come from the server, so the line says what was actually found rather than
// a guess at how far along the answer is.
function describe(step: ProgressStep): string {
  const number = (key: string) => (typeof step[key] === 'number' ? (step[key] as number) : null)
  switch (step.step) {
    case 'start':
      return `Hledám podklady pro ${number('candidates') ?? 40} kandidátů`
    case 'retrieval': {
      const graded = number('graded')
      const cached = number('cached')
      const parts = [`${number('candidates') ?? 0} kandidátů ohodnoceno`]
      if (graded != null && cached != null && cached > 0) parts.push(`${cached} známek z cache`)
      return parts.join(', ')
    }
    case 'gate':
      return `Branou relevance prošlo ${number('passed') ?? 0} z ${number('candidates') ?? 0}`
    case 'context':
      return `Kontext: ${number('sources') ?? 0} zdrojů, ${number('tokens') ?? 0} tokenů`
    case 'generation':
      return `Model ${String(step.model ?? '')} skládá odpověď`
    case 'validation':
      return `Kontrola citací: ${number('verified') ?? 0} z ${number('statements') ?? 0} vět ověřeno`
    case 'cache':
      return 'Tahle otázka už byla zodpovězená, odpověď je z cache'
    default:
      return String(step.step)
  }
}

export function AnswerProgress({ steps }: Props) {
  if (steps.length === 0) return null
  return (
    <ol className="mt-3 space-y-1 text-sm">
      {steps.map((step, index) => {
        const last = index === steps.length - 1
        return (
          <li key={`${step.step}-${index}`} className={clsx('flex items-center gap-2', last ? 'text-slate-700' : 'text-slate-500')}>
            {last ? (
              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-600" />
            ) : (
              <Check className="h-3.5 w-3.5 shrink-0 text-green-600" />
            )}
            <span>{describe(step)}</span>
          </li>
        )
      })}
    </ol>
  )
}
