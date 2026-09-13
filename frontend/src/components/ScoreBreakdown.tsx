import { formatScore, MAX_GRADE } from '../lib/modes'
import type { Branch, Hit } from '../types'

interface Props {
  hit: Hit
  branches: Branch[]
  fetch: number
  rrfK?: number
}

// Why a chunk sits where it sits: its place in each branch, the fusion sum and,
// after reranking, the grade the model gave it.
export function ScoreBreakdown({ hit, branches, fetch, rrfK = 60 }: Props) {
  const ran = (branch: Branch) => branches.includes(branch)
  const row = (label: string, rank: number | null, score: number | null, scoreLabel: string, branch: Branch) => (
    <tr className="border-t border-slate-100">
      <td className="py-1 pr-3 font-medium text-slate-600">{label}</td>
      {!ran(branch) ? (
        <td colSpan={2} className="py-1 text-slate-400">
          tato větev v tomto režimu neběžela
        </td>
      ) : rank == null ? (
        <td colSpan={2} className="py-1 text-slate-400">
          není mezi {fetch} nejlepšími kandidáty této větve
        </td>
      ) : (
        <>
          <td className="py-1 pr-3">
            pořadí <b>{rank}</b>
          </td>
          <td className="py-1">
            {scoreLabel} <b>{formatScore(score)}</b>
          </td>
        </>
      )}
    </tr>
  )

  const terms: string[] = []
  if (hit.vector_rank != null) terms.push(`1/(${rrfK}+${hit.vector_rank})`)
  if (hit.fts_rank != null) terms.push(`1/(${rrfK}+${hit.fts_rank})`)

  return (
    <div className="rounded-md bg-slate-50 p-3 text-xs">
      <table className="w-full">
        <tbody>
          {row('Sémantické (význam)', hit.vector_rank, hit.vector_score, 'kosinová podobnost', 'vector')}
          {row('Fulltext (slova)', hit.fts_rank, hit.fts_score, 'skóre', 'fts')}
          {hit.rrf_score != null && (
            <tr className="border-t border-slate-100">
              <td className="py-1 pr-3 font-medium text-slate-600">Hybridní (RRF)</td>
              <td colSpan={2} className="py-1">
                {terms.join(' + ')} = <b>{formatScore(hit.rrf_score)}</b>
              </td>
            </tr>
          )}
          {hit.rerank_grade != null && (
            <tr className="border-t border-slate-100">
              <td className="py-1 pr-3 font-medium text-slate-600">Reranking</td>
              <td colSpan={2} className="py-1">
                známka <b>{hit.rerank_grade}/{MAX_GRADE}</b>
                {hit.candidate_rank != null && <> · mezi kandidáty byl {hit.candidate_rank}.</>}
                {hit.rerank_reason && <span className="block italic text-slate-600">„{hit.rerank_reason}“</span>}
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <p className="mt-2 text-slate-500">
        {hit.lexical_match
          ? 'Text obsahuje některé z hledaných slov (v některém tvaru).'
          : 'Text neobsahuje žádné z hledaných slov – shoda je čistě významová.'}
      </p>
    </div>
  )
}
