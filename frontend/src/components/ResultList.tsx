import { Fragment } from 'react'
import { branchesOf, MAX_GRADE, MODE_INFO, scoreOf } from '../lib/modes'
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
  const minGrade = mode === 'rerank' ? response.debug.rerank?.min_grade : undefined
  // Grades have a fixed scale; a bar relative to the best grade would make a 2 look like a 3.
  const maxScore = mode === 'rerank' ? MAX_GRADE : Math.max(0, ...response.hits.map((hit) => scoreOf(hit, mode) ?? 0))
  const below = (grade: number | null | undefined) => minGrade != null && (grade ?? 0) < minGrade

  if (response.hits.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-center text-sm text-slate-500">
        <p className="font-medium text-slate-600">{MODE_INFO[mode].label}: žádný výsledek</p>
        {(emptyReason ?? response.debug.rerank_error) && <p className="mt-1">{emptyReason ?? response.debug.rerank_error}</p>}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {response.hits.map((hit, index) => {
        const firstBelow =
          below(hit.rerank_grade) && (index === 0 || !below(response.hits[index - 1].rerank_grade))
        return (
          <Fragment key={hit.chunk_id}>
            {firstBelow && (
              <div className="border-t-2 border-dashed border-amber-300 pt-2 text-xs text-amber-800">
                Pod prahem relevance: známka nižší než {minGrade}. Do odpovědi by tyto úryvky nešly.
              </div>
            )}
            <ResultCard
              hit={hit}
              mode={mode}
              branches={branches}
              fetch={response.fetch}
              maxScore={maxScore}
              position={index + 1}
              compact={compact}
              tag={tags?.get(hit.chunk_id)}
              belowThreshold={below(hit.rerank_grade)}
            />
          </Fragment>
        )
      })}
    </div>
  )
}
