import clsx from 'clsx'
import { ExternalLink, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { COST_INFO, STEPS, type Block, type Detail } from '../lib/architecture'

interface Props {
  detail: Detail | null
  onClose: () => void
}

// The panel next to the diagram. Empty state invites the first click; a
// selected step or topic gets every section that has content, and nothing
// else — an empty "Záludnosti" heading would look like a missing answer.
export function StepDetail({ detail, onClose }: Props) {
  if (!detail) {
    return (
      <div className="flex h-full min-h-[16rem] items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-400 lg:sticky lg:top-4">
        Klikněte na krok ve schématu nebo na téma dole — podrobnosti se otevřou tady.
      </div>
    )
  }

  const step = STEPS.find((item) => item.id === detail.id)
  const cost = step ? COST_INFO[step.cost] : null

  return (
    <div className="space-y-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-base font-semibold text-slate-900">{detail.title}</h3>
          <p className="mt-0.5 text-sm text-slate-600">{detail.lead}</p>
        </div>
        <button type="button" onClick={onClose} className="shrink-0 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600" aria-label="Zavřít">
          <X className="h-4 w-4" />
        </button>
      </div>

      {(cost || detail.tech.length > 0) && (
        <div className="flex flex-wrap items-center gap-1.5">
          {cost && <span className={clsx('rounded-full px-2 py-0.5 text-[11px] font-medium', cost.badge)}>{cost.label}</span>}
          {detail.tech.map((item) => (
            <span key={item} className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-mono text-slate-600">
              {item}
            </span>
          ))}
        </div>
      )}

      {detail.what.length > 0 && (
        <Section title="Co se tu děje">
          <ul className="list-disc space-y-1 pl-4 text-sm text-slate-700">
            {detail.what.map((line, index) => (
              <li key={index}>{line}</li>
            ))}
          </ul>
        </Section>
      )}

      {detail.blocks?.map((block, index) => <BlockView key={index} block={block} />)}

      {detail.gotchas && detail.gotchas.length > 0 && (
        <Section title="Záludnosti">
          <dl className="space-y-2">
            {detail.gotchas.map((item) => (
              <div key={item.title} className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs">
                <dt className="font-medium text-amber-900">{item.title}</dt>
                <dd className="mt-0.5 text-amber-800">{item.text}</dd>
              </div>
            ))}
          </dl>
        </Section>
      )}

      {detail.safeguard && detail.safeguard.length > 0 && (
        <Section title="🛡 Bezpečnostní opatření">
          <ul className="list-disc space-y-1 pl-4 text-sm text-slate-700">
            {detail.safeguard.map((line, index) => (
              <li key={index}>{line}</li>
            ))}
          </ul>
        </Section>
      )}

      {detail.numbers && detail.numbers.length > 0 && (
        <Section title="Čísla">
          <dl className="grid grid-cols-2 gap-2 text-xs">
            {detail.numbers.map((item) => (
              <div key={item.label} className="rounded-md bg-slate-50 p-2">
                <dt className="text-slate-500">{item.label}</dt>
                <dd className="font-mono font-medium text-slate-800">{item.value}</dd>
              </div>
            ))}
          </dl>
        </Section>
      )}

      {detail.files.length > 0 && (
        <Section title="Soubory">
          <ul className="space-y-0.5">
            {detail.files.map((file) => (
              <li key={file} className="flex items-center gap-1 truncate font-mono text-xs text-slate-500">
                <ExternalLink className="h-3 w-3 shrink-0" />
                {file}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h4>
      {children}
    </div>
  )
}

function BlockView({ block }: { block: Block }) {
  if (block.kind === 'text') {
    return (
      <Section title={block.title ?? ''}>
        <div className="space-y-1.5 text-sm text-slate-700">
          {block.text?.map((paragraph, index) => (
            <p key={index}>{paragraph}</p>
          ))}
        </div>
      </Section>
    )
  }
  if (block.kind === 'note') {
    return (
      <div className="rounded-md border border-blue-200 bg-blue-50 p-2 text-xs text-blue-900">
        {block.title && <p className="mb-0.5 font-medium">{block.title}</p>}
        {block.text?.map((paragraph, index) => (
          <p key={index}>{paragraph}</p>
        ))}
      </div>
    )
  }
  if (block.kind === 'code') {
    return (
      <Section title={block.title ?? 'Kód'}>
        <pre className="overflow-x-auto rounded-md bg-slate-900 p-2.5 text-[11px] leading-snug text-slate-100">
          <code>{block.code}</code>
        </pre>
      </Section>
    )
  }
  if (block.kind === 'table' && block.table) {
    return (
      <Section title={block.title ?? ''}>
        <div className="overflow-x-auto rounded-md border border-slate-200">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-slate-50">
                {block.table.head.map((cell) => (
                  <th key={cell} className="border-b border-slate-200 px-2 py-1 text-left font-medium text-slate-600">
                    {cell}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.table.rows.map((row, rowIndex) => (
                <tr key={rowIndex} className="border-t border-slate-100">
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex} className="px-2 py-1 font-mono text-slate-700">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    )
  }
  return null
}
