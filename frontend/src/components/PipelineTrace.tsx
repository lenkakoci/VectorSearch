import clsx from 'clsx'
import { CHECK_INFO } from '../lib/answers'
import type { AnswerRequest, AnswerResponse, CheckResult } from '../types'

interface Props {
  answer: AnswerResponse
  request?: AnswerRequest
  ms?: number
  open: boolean
  onToggle: (open: boolean) => void
}

interface Step {
  name: string
  detail: string
  count?: string
  ms?: number | null
  skipped?: boolean
}

function ms(value: number | null | undefined): string {
  return value == null ? '' : `${Math.round(value)} ms`
}

// The whole chain in the order it ran, with the number each step produced.
// This is the panel to show a colleague who asks why an answer says what it
// says: every step is a count you can check against the sources below.
function stepsOf(answer: AnswerResponse): Step[] {
  const trace = answer.trace
  const retrieval = trace.retrieval ?? {}
  const rerank = trace.rerank
  const gate = trace.gate
  const context = trace.context
  const generation = trace.generation
  const validation = trace.validation
  const words = (retrieval.query_words as string[] | undefined) ?? []

  const steps: Step[] = [
    {
      name: 'Dotaz',
      detail: words.length ? `slova: ${words.join(', ')}` : 'otázka beze slov k hledání',
      count: `${answer.question.length} znaků`,
    },
    {
      name: 'Fulltext',
      detail: `libovolné slovo, řazeno podle IDF · ${retrieval.tsquery?.any ?? '–'}`,
      count: `${retrieval.fts_any_candidates ?? 0} kandidátů`,
      ms: retrieval.fts_any_ms,
    },
    {
      name: 'Vektor',
      detail: retrieval.embedding_cached ? 'embedding dotazu z cache' : `embedding dotazu ${ms(retrieval.embed_ms)}`,
      count: `${retrieval.vector_candidates ?? 0} kandidátů`,
      ms: retrieval.vector_ms,
    },
    {
      name: 'Výběr kandidátů',
      detail: 'dvacet nejlepších z každé větve, pořadí sloučeno metodou RRF',
      count: `${gate?.candidates ?? 0} kandidátů`,
    },
  ]

  if (rerank) {
    steps.push({
      name: 'Reranking',
      detail: `${rerank.reranker} · ${rerank.model ?? '–'} · ${rerank.graded} nově, ${rerank.cached} z cache, ${rerank.calls} volání`,
      count: `${rerank.candidates} známek`,
      ms: rerank.ms,
    })
  }

  if (gate) {
    steps.push({
      name: 'Brána relevance',
      detail: `pod známkou ${gate.min_grade} se do odpovědi nedostane nic`,
      count: `${gate.passed} z ${gate.candidates} prošlo`,
    })
  }

  if (context) {
    const dropped = [
      context.dropped_below_gate ? `${context.dropped_below_gate} pod branou` : '',
      context.dropped_per_document ? `${context.dropped_per_document} nad limit na dokument` : '',
      context.dropped_over_budget ? `${context.dropped_over_budget} nad rozpočet tokenů` : '',
    ].filter(Boolean)
    steps.push({
      name: 'Kontext',
      detail: `${context.documents} dokumentů, ${context.neighbours} sousedů, ${context.tokens} tokenů${
        dropped.length ? ` · vynecháno: ${dropped.join(', ')}` : ''
      }`,
      count: `${context.sources} zdrojů`,
    })
  } else {
    steps.push({ name: 'Kontext', detail: 'nesestavoval se, brána nepustila nic', count: '0 zdrojů', skipped: true })
  }

  if (generation) {
    const cached = trace.cache === 'hit'
    steps.push({
      name: 'Odpověď',
      detail: cached
        ? `z cache: stejná otázka už byla zodpovězena modelem ${generation.model}, prompt v${generation.prompt_version}`
        : `${generation.model} · prompt v${generation.prompt_version} · model hlásí „${generation.model_status}“`,
      count: `${answer.statements.length} vět`,
      ms: cached ? null : generation.ms,
      skipped: cached,
    })
  } else {
    steps.push({ name: 'Odpověď', detail: 'model se nevolal, nebylo z čeho odpovídat', count: '0 vět', skipped: true })
  }

  if (validation) {
    const failed = (Object.entries(validation.checks) as [CheckResult, number][])
      .filter(([check, count]) => check !== 'verified' && count > 0)
      .map(([check, count]) => `${count}× ${CHECK_INFO[check]}`)
    steps.push({
      name: 'Kontrola citací',
      detail: failed.length ? failed.join(', ') : 'každý citát i každé číslo nalezeno v citovaném zdroji',
      count: `${validation.verified} z ${validation.statements} ověřeno`,
    })
  }

  return steps
}

export function PipelineTrace({ answer, request, ms: total, open, onToggle }: Props) {
  const steps = stepsOf(answer)
  const prompt = typeof answer.trace.prompt === 'string' ? answer.trace.prompt : null

  return (
    <details
      open={open}
      onToggle={(event) => onToggle((event.target as HTMLDetailsElement).open)}
      className="rounded-lg border border-slate-200 bg-white shadow-sm"
    >
      <summary className="cursor-pointer select-none px-4 py-2 text-sm font-semibold text-slate-700">
        Expert: průběh odpovědi
        <span className="ml-2 text-xs font-normal text-slate-400">
          {answer.trace.total_ms != null && `server ${(answer.trace.total_ms / 1000).toFixed(1)} s`}
          {total != null && ` · celkem ${(total / 1000).toFixed(1)} s`}
        </span>
      </summary>

      <div className="space-y-4 border-t border-slate-100 px-4 py-3">
        <ol className="space-y-1">
          {steps.map((step, index) => (
            <li
              key={step.name}
              className={clsx(
                'grid grid-cols-[1.5rem_9rem_1fr_auto_auto] items-baseline gap-2 border-l-2 py-1 pl-2 text-xs',
                step.skipped ? 'border-slate-200 text-slate-400' : 'border-blue-200 text-slate-700',
              )}
            >
              <span className="text-slate-400">{index + 1}.</span>
              <span className="font-semibold text-slate-800">{step.name}</span>
              <span className="text-slate-500">{step.detail}</span>
              <span className="whitespace-nowrap font-mono">{step.count}</span>
              <span className="w-16 whitespace-nowrap text-right font-mono text-slate-400">{ms(step.ms)}</span>
            </li>
          ))}
        </ol>

        {request && (
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Požadavek</h3>
            <pre className="overflow-x-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(request, null, 2)}</pre>
          </div>
        )}

        {prompt && (
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Prompt, jak ho dostal model</h3>
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs">{prompt}</pre>
          </div>
        )}

        {answer.trace.raw_answer != null && (
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Surová odpověď modelu, před kontrolou</h3>
            <pre className="max-h-96 overflow-auto rounded bg-slate-50 p-2 text-xs">
              {JSON.stringify(answer.trace.raw_answer, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </details>
  )
}
