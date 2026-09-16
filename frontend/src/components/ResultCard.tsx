import clsx from 'clsx'
import { ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { Highlight } from '../lib/highlight'
import { api } from '../services/api'
import { formatModeScore, MAX_GRADE, MODE_INFO, scoreOf } from '../lib/modes'
import type { Branch, Hit, Mode } from '../types'
import { ContextView } from './ContextView'
import { DocumentInfo } from './DocumentInfo'
import { ScoreBreakdown } from './ScoreBreakdown'

export interface Tag {
  letter: string
  className: string
}

interface Props {
  hit: Hit
  mode: Mode
  branches: Branch[]
  fetch: number
  maxScore: number
  position: number
  compact?: boolean
  tag?: Tag
  belowThreshold?: boolean
}

type Panel = 'none' | 'full' | 'context' | 'document' | 'why'

interface Badge {
  label: string
  className: string
  title: string
}

const BADGE = {
  words: 'bg-blue-100 text-blue-800',
  meaning: 'bg-purple-100 text-purple-800',
  both: 'bg-green-100 text-green-800',
  none: 'bg-amber-100 text-amber-800',
  annex: 'bg-slate-200 text-slate-700',
}

const GRADE_CLASS: Record<number, string> = {
  3: 'bg-green-600 text-white',
  2: 'bg-teal-600 text-white',
  1: 'bg-amber-200 text-amber-900',
  0: 'bg-slate-200 text-slate-600',
}

// Which method found the chunk. With both branches run, membership in each
// candidate list decides; with one branch, lexical_match still says whether
// any of the query's words is there at all.
function foundBadges(hit: Hit, branches: Branch[]): Badge[] {
  const inWords = hit.fts_rank != null
  const inMeaning = hit.vector_rank != null
  if (branches.length === 2) {
    if (inWords && inMeaning) return [{ label: 'obojí', className: BADGE.both, title: 'Našel fulltext i sémantické hledání' }]
    if (inWords) return [{ label: 'jen slova', className: BADGE.words, title: 'Našel jen fulltext; sémanticky není mezi kandidáty' }]
    const badges: Badge[] = [{ label: 'jen význam', className: BADGE.meaning, title: 'Našlo jen sémantické hledání' }]
    if (!hit.lexical_match) badges.push({ label: 'bez shody slov', className: BADGE.none, title: 'Žádné hledané slovo v textu není' })
    return badges
  }
  if (branches[0] === 'fts') return [{ label: 'slova', className: BADGE.words, title: 'Nalezeno podle slov' }]
  return hit.lexical_match
    ? [{ label: 'význam', className: BADGE.meaning, title: 'Nalezeno podle významu' }, { label: 'obsahuje hledaná slova', className: 'bg-slate-100 text-slate-600', title: '' }]
    : [{ label: 'význam', className: BADGE.meaning, title: 'Nalezeno podle významu' }, { label: 'bez shody slov', className: BADGE.none, title: 'Žádné hledané slovo v textu není – shoda je čistě významová' }]
}

function pages(hit: Hit): string {
  if (!hit.page_from) return ''
  return hit.page_to && hit.page_to !== hit.page_from ? `s. ${hit.page_from}–${hit.page_to}` : `s. ${hit.page_from}`
}

export function ResultCard({ hit, mode, branches, fetch, maxScore, position, compact, tag, belowThreshold }: Props) {
  const [panel, setPanel] = useState<Panel>('none')
  const score = scoreOf(hit, mode)
  const percent = score != null && maxScore > 0 ? Math.max(4, Math.round((score / maxScore) * 100)) : 0
  const sections = (hit.section ?? '').split(' > ').filter(Boolean)
  const toggle = (next: Panel) => setPanel((current) => (current === next ? 'none' : next))
  const metadata = [hit.author, hit.organization, hit.municipality, hit.report_type, hit.report_date].filter(Boolean)
  const grade = hit.rerank_grade

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
      className={clsx(
        'rounded-lg border bg-white shadow-sm transition-opacity',
        tag ? 'border-slate-300' : 'border-slate-200',
        compact ? 'p-3' : 'p-4',
        belowThreshold && 'opacity-60 hover:opacity-100',
      )}
    >
      <header className="flex items-start gap-2">
        <span className="mt-0.5 w-6 shrink-0 text-right text-sm font-semibold text-slate-400">{position}.</span>
        {tag && (
          <span className={clsx('mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold', tag.className)} title="Stejný úryvek v jiném sloupci">
            {tag.letter}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <h3 className={clsx('font-semibold leading-snug text-slate-900', compact ? 'text-sm' : 'text-base')} title={hit.title ?? ''}>
            {hit.title ?? '(bez názvu)'}
          </h3>
          <div className="mt-1 flex flex-wrap items-center gap-1 text-[11px]">
            {grade != null && (
              <span className={clsx('rounded-full px-2 py-0.5 font-semibold', GRADE_CLASS[grade] ?? GRADE_CLASS[0])} title="Známka od rerankeru">
                známka {grade}/{MAX_GRADE}
              </span>
            )}
            {foundBadges(hit, branches).map((badge) => (
              <span key={badge.label} title={badge.title} className={clsx('rounded-full px-2 py-0.5 font-medium', badge.className)}>
                {badge.label}
              </span>
            ))}
            {hit.content_kind === 'annex' && (
              <span className={clsx('rounded-full px-2 py-0.5 font-medium uppercase', BADGE.annex)} title="Přílohová část zprávy (bez vektoru)">
                příloha
              </span>
            )}
          </div>
        </div>
      </header>

      <div className={clsx('mt-2 flex flex-wrap items-center gap-x-1 text-slate-500', compact ? 'text-[11px]' : 'text-xs')}>
        {sections.length === 0 && <span>bez sekce</span>}
        {sections.map((part, index) => (
          <span key={index} className="inline-flex items-center gap-1">
            {index > 0 && <ChevronRight className="h-3 w-3 text-slate-300" />}
            <span className={clsx(index === sections.length - 1 && 'font-medium text-slate-700')}>{part}</span>
          </span>
        ))}
        <span className="mx-1 text-slate-300">·</span>
        {pages(hit) && <span>{pages(hit)}</span>}
        {pages(hit) && <span className="mx-1 text-slate-300">·</span>}
        <span className="font-mono">chunk #{hit.chunk_index}</span>
      </div>

      <div className="mt-2 flex items-center gap-2 text-xs">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100" title={`${MODE_INFO[mode].scoreLabel} (lišta je relativní k nejlepšímu výsledku)`}>
          <div className="h-full rounded-full bg-blue-500" style={{ width: `${percent}%` }} />
        </div>
        <span className="w-20 text-right font-mono text-slate-600" title={MODE_INFO[mode].scoreLabel}>
          {formatModeScore(hit, mode)}
        </span>
      </div>

      {hit.rerank_reason && grade != null && (
        <p className={clsx('mt-2 italic text-slate-600', compact ? 'text-xs' : 'text-sm')}>
          Reranker: „{hit.rerank_reason}“
          {hit.candidate_rank != null && <span className="not-italic text-slate-400"> · kandidát {hit.candidate_rank}.</span>}
        </p>
      )}

      <p className={clsx('mt-2 text-slate-700', compact ? 'text-xs' : 'text-sm', panel !== 'full' && (compact ? 'line-clamp-4' : 'line-clamp-3'))}>
        {panel === 'full' ? (
          <span className="whitespace-pre-wrap">{hit.chunk_raw}</span>
        ) : hit.headline ? (
          <Highlight text={hit.headline} />
        ) : (
          <>{hit.snippet}…</>
        )}
      </p>

      {!compact && metadata.length > 0 && <p className="mt-2 text-xs text-slate-500">{metadata.join(' · ')}</p>}

      <div className="mt-2 flex flex-wrap gap-1 text-xs">
        {action(panel === 'full' ? 'Skrýt celý text' : 'Celý text', 'full')}
        {action('Kontext ±1', 'context')}
        {action('O dokumentu', 'document')}
        {action('Proč nalezeno', 'why')}
        <a
          href={api.pdfUrl(hit.document_id, hit.page_from)}
          target="_blank"
          rel="noreferrer"
          className="rounded px-2 py-0.5 text-blue-700 hover:bg-slate-100"
          title="Otevře zdrojové PDF na straně tohoto úryvku"
        >
          {hit.page_from ? `PDF, s. ${hit.page_from}` : 'PDF'}
        </a>
      </div>

      {panel === 'context' && (
        <div className="mt-2">
          <ContextView documentId={hit.document_id} chunkIndex={hit.chunk_index} />
        </div>
      )}
      {panel === 'document' && (
        <div className="mt-2">
          <DocumentInfo documentId={hit.document_id} />
        </div>
      )}
      {panel === 'why' && (
        <div className="mt-2">
          <ScoreBreakdown hit={hit} branches={branches} fetch={fetch} />
        </div>
      )}
    </article>
  )
}
