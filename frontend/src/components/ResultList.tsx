import { branchesOf, MODE_INFO, scoreOf } from '../lib/modes'
import type { SearchResponse } from '../types'
import { ResultCard, type Tag } from './ResultCard'

interface Props {
  response: SearchResponse
  compact?: boolean
  tags?: Map<string, Tag>
  emptyReason?: string
}

export function ResultList({ response, compact, tags, emptyReason }: Props) {
  const mode = response.mode
  const branches = branchesOf(mode)
  const maxScore = Math.max(0, ...response.hits.map((hit) => scoreOf(hit, mode) ?? 0))

  if (response.hits.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-center text-sm text-slate-500">
        <p className="font-medium text-slate-600">{MODE_INFO[mode].label}: žádný výsledek</p>
        {emptyReason && <p className="mt-1">{emptyReason}</p>}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {response.hits.map((hit, index) => (
        <ResultCard
          key={hit.chunk_id}
          hit={hit}
          mode={mode}
          branches={branches}
          fetch={response.fetch}
          maxScore={maxScore}
          position={index + 1}
          compact={compact}
          tag={tags?.get(hit.chunk_id)}
        />
      ))}
    </div>
  )
}
