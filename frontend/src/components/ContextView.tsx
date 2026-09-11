import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { api } from '../services/api'
import type { ContextResponse } from '../types'

interface Props {
  documentId: string
  chunkIndex: number
}

function pages(from: number | null, to: number | null): string {
  if (!from) return ''
  return to && to !== from ? `s. ${from}–${to}` : `s. ${from}`
}

// The chunks before and after a hit, in reading order, so a passage can be
// read in its surroundings without opening the report.
export function ContextView({ documentId, chunkIndex }: Props) {
  const [data, setData] = useState<ContextResponse | null>(null)
  const [reach, setReach] = useState(1)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .context(documentId, chunkIndex, reach, reach)
      .then((response) => !cancelled && setData(response))
      .catch((err: Error) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [documentId, chunkIndex, reach])

  if (error) return <p className="text-xs text-red-600">{error}</p>
  if (!data) return <p className="text-xs text-slate-400">načítám kontext…</p>

  return (
    <div className="space-y-2 text-xs">
      <div className="flex items-center gap-3 text-slate-500">
        <span>Sousední chunky v pořadí dokumentu</span>
        <button
          type="button"
          onClick={() => setReach((value) => Math.min(5, value + 1))}
          disabled={reach >= 5}
          className="text-blue-600 hover:underline disabled:text-slate-300"
        >
          rozšířit (±{reach + 1})
        </button>
      </div>
      {data.chunks.map((chunk) => (
        <div
          key={chunk.chunk_index}
          className={clsx(
            'rounded-md border p-2',
            chunk.is_hit ? 'border-blue-300 bg-blue-50' : 'border-slate-200 bg-white text-slate-600',
          )}
        >
          <div className="mb-1 flex flex-wrap gap-x-2 text-[11px] text-slate-500">
            <span className="font-mono">#{chunk.chunk_index}</span>
            {chunk.section && <span>{chunk.section}</span>}
            {pages(chunk.page_from, chunk.page_to) && <span>{pages(chunk.page_from, chunk.page_to)}</span>}
            {chunk.content_kind === 'annex' && <span className="uppercase">příloha</span>}
            {chunk.is_hit && <span className="font-semibold text-blue-700">nalezený chunk</span>}
          </div>
          <p className="whitespace-pre-wrap">{chunk.chunk_raw}</p>
        </div>
      ))}
    </div>
  )
}
