import clsx from 'clsx'
import { ChevronRight, Quote } from 'lucide-react'
import { useEffect, useState } from 'react'
import { anchorOf, pagesOf, ROLE_INFO } from '../lib/answers'
import { QuoteHighlight } from '../lib/highlight'
import { MAX_GRADE } from '../lib/modes'
import type { AnswerSource } from '../types'
import { api } from '../services/api'
import { ContextView } from './ContextView'
import { DocumentInfo } from './DocumentInfo'

export interface Highlighted {
  id: number
  quotes: string[]
}

interface Props {
  sources: AnswerSource[]
  highlight: Highlighted | null
  title?: string
  note?: string
}

type Panel = 'none' | 'context' | 'document'

const GRADE_CLASS: Record<number, string> = {
  3: 'bg-green-600 text-white',
  2: 'bg-teal-600 text-white',
  1: 'bg-amber-200 text-amber-900',
  0: 'bg-slate-200 text-slate-600',
}

function SourceCard({ source, highlight }: { source: AnswerSource; highlight: Highlighted | null }) {
  const active = highlight?.id === source.id
  const [open, setOpen] = useState(source.cited)
  const [panel, setPanel] = useState<Panel>('none')
  const sections = (source.section ?? '').split(' > ').filter(Boolean)
  const metadata = [source.municipality, source.report_type, source.organization, source.report_date].filter(Boolean)
  const quotes = active ? highlight!.quotes : []

  // A citation opens the source it points at, even when it was not cited by
  // the sentence that is expanded by default.
  useEffect(() => {
    if (active) setOpen(true)
  }, [active])

  const toggle = (next: Panel) => setPanel((current) => (current === next ? 'none' : next))
  const action = (label: string, key: Panel) => (
    <button
      type="button"
      onClick={() => toggle(key)}
      className={clsx('rounded px-2 py-0.5 hover:bg-slate-100', panel === key ? 'bg-slate-200 text-slate-900' : 'text-blue-700')}
    >
      {label}
    </button>
  )

  return (
    <article
      id={anchorOf(source.id)}
      className={clsx(
        'scroll-mt-4 rounded-lg border bg-white p-3 shadow-sm transition',
        active ? 'border-blue-400 ring-2 ring-blue-200' : source.cited ? 'border-slate-300' : 'border-slate-200',
        !source.cited && !open && 'bg-slate-50',
      )}
    >
      <header className="flex items-start gap-2">
        <span
          className={clsx(
            'mt-0.5 inline-flex h-6 min-w-[1.5rem] shrink-0 items-center justify-center rounded px-1 text-sm font-semibold',
            source.cited ? 'bg-blue-600 text-white' : 'bg-slate-200 text-slate-600',
          )}
        >
          {source.id}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold leading-snug text-slate-900" title={source.title ?? ''}>
            {source.title ?? '(bez názvu)'}
          </h3>
          <div className="mt-1 flex flex-wrap items-center gap-1 text-[11px]">
            {source.cited && (
              <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 font-medium text-blue-800">
                <Quote className="h-3 w-3" />
                citováno
              </span>
            )}
            {source.rerank_grade != null && (
              <span
                className={clsx('rounded-full px-2 py-0.5 font-semibold', GRADE_CLASS[source.rerank_grade] ?? GRADE_CLASS[0])}
                title={source.rerank_reason ?? 'Známka od rerankeru'}
              >
                známka {source.rerank_grade}/{MAX_GRADE}
              </span>
            )}
            {source.role !== 'nalezeno' && (
              <span className="rounded-full bg-slate-200 px-2 py-0.5 font-medium text-slate-700" title={ROLE_INFO[source.role] ?? ''}>
                {source.role}
              </span>
            )}
            {source.content_kind === 'annex' && (
              <span className="rounded-full bg-slate-200 px-2 py-0.5 font-medium uppercase text-slate-700" title="Přílohová část zprávy">
                příloha
              </span>
            )}
          </div>
        </div>
      </header>

      <div className="mt-2 flex flex-wrap items-center gap-x-1 text-[11px] text-slate-500">
        {sections.length === 0 && <span>bez sekce</span>}
        {sections.map((part, index) => (
          <span key={index} className="inline-flex items-center gap-1">
            {index > 0 && <ChevronRight className="h-3 w-3 text-slate-300" />}
            <span className={clsx(index === sections.length - 1 && 'font-medium text-slate-700')}>{part}</span>
          </span>
        ))}
        {pagesOf(source) && (
          <>
            <span className="mx-1 text-slate-300">·</span>
            <span>{pagesOf(source)}</span>
          </>
        )}
        <span className="mx-1 text-slate-300">·</span>
        <span className="font-mono">chunk #{source.chunk_index}</span>
      </div>

      <p className={clsx('mt-2 text-sm text-slate-700', !open && 'line-clamp-2')}>
        {open ? (
          <span className="whitespace-pre-wrap">
            <QuoteHighlight text={source.chunk_raw} quotes={quotes} />
          </span>
        ) : (
          source.chunk_raw.slice(0, 220)
        )}
      </p>

      {open && metadata.length > 0 && <p className="mt-2 text-xs text-slate-500">{metadata.join(' · ')}</p>}

      <div className="mt-2 flex flex-wrap gap-1 text-xs">
        <button type="button" onClick={() => setOpen((value) => !value)} className="rounded px-2 py-0.5 text-blue-700 hover:bg-slate-100">
          {open ? 'Sbalit' : 'Celý text'}
        </button>
        {action('Kontext ±1', 'context')}
        {action('O dokumentu', 'document')}
        <a
          href={api.pdfUrl(source.document_id, source.page_from)}
          target="_blank"
          rel="noreferrer"
          className="rounded px-2 py-0.5 text-blue-700 hover:bg-slate-100"
          title="Otevře zdrojové PDF na straně, kterou citace uvádí"
        >
          {source.page_from ? `PDF, s. ${source.page_from}` : 'PDF'}
        </a>
      </div>

      {panel === 'context' && (
        <div className="mt-2">
          <ContextView documentId={source.document_id} chunkIndex={source.chunk_index} />
        </div>
      )}
      {panel === 'document' && (
        <div className="mt-2">
          <DocumentInfo documentId={source.document_id} />
        </div>
      )}
    </article>
  )
}

export function SourceList({ sources, highlight, title = 'Zdroje', note }: Props) {
  if (sources.length === 0) return null
  const cited = sources.filter((source) => source.cited).length
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold text-slate-700">
        {title}
        <span className="ml-2 text-xs font-normal text-slate-500">
          {note ?? `${sources.length} úryvků v kontextu, z toho ${cited} citovaných`}
        </span>
      </h2>
      <div className="space-y-2">
        {sources.map((source) => (
          <SourceCard key={source.id} source={source} highlight={highlight} />
        ))}
      </div>
    </section>
  )
}
