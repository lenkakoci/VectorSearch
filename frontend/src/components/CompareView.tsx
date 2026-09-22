import clsx from 'clsx'
import { Info } from 'lucide-react'
import { useMemo } from 'react'
import { COMPARE_MODES, MODE_INFO, MODES } from '../lib/modes'
import { TAG_PALETTE } from '../lib/tone'
import type { CompareResponse, Mode, RequestFilters, SearchResponse } from '../types'
import { ResultList } from './ResultList'
import type { Tag } from './ResultCard'

interface Props {
  data: CompareResponse
  filters: RequestFilters
}

export function modesOf(data: CompareResponse): Mode[] {
  return data.rerank ? COMPARE_MODES : MODES
}

export function responseOf(data: CompareResponse, mode: Mode): SearchResponse {
  return (mode === 'rerank' ? data.rerank : data[mode]) as SearchResponse
}

// Chunks that appear in more than one column get the same letter and colour,
// so the overlap between the methods is visible at a glance.
function assignTags(data: CompareResponse, modes: Mode[]): Map<string, Tag> {
  const seen = new Map<string, number>()
  for (const mode of modes) {
    for (const hit of responseOf(data, mode).hits) seen.set(hit.chunk_id, (seen.get(hit.chunk_id) ?? 0) + 1)
  }
  const tags = new Map<string, Tag>()
  let next = 0
  for (const mode of modes) {
    for (const hit of responseOf(data, mode).hits) {
      if ((seen.get(hit.chunk_id) ?? 0) > 1 && !tags.has(hit.chunk_id)) {
        tags.set(hit.chunk_id, { letter: String.fromCharCode(65 + (next % 26)), className: TAG_PALETTE[next % TAG_PALETTE.length] })
        next += 1
      }
    }
  }
  return tags
}

function emptyReason(mode: Mode, response: SearchResponse, filters: RequestFilters): string {
  if (mode === 'fts') {
    const lexemes = response.debug.tsquery?.czech
    return lexemes
      ? `Žádný chunk neobsahuje všechna hledaná slova zároveň (hledané lexémy: ${lexemes}). Zkuste méně slov nebo spojku „or“.`
      : 'Dotaz neobsahuje žádné slovo, které by šlo hledat (samá stopslova).'
  }
  if (mode === 'vector') {
    return filters.content_kind === 'annex'
      ? 'Přílohy nemají vektor, sémantické hledání je nemůže najít – to je záměr, ne chyba.'
      : 'Sémantické hledání nevrátilo nic v rámci zvolených filtrů.'
  }
  if (mode === 'rerank') {
    return response.debug.rerank_error
      ? `Reranking selhal: ${response.debug.rerank_error}`
      : 'Hybridní hledání nevrátilo žádné kandidáty k ohodnocení.'
  }
  return 'Ani jedna větev nic nenašla.'
}

function timing(response: SearchResponse): string {
  const debug = response.debug
  const parts: string[] = []
  if (debug.embed_ms != null) parts.push(`embedding ${debug.embed_ms} ms${debug.embedding_cached ? ' (cache)' : ''}`)
  if (debug.vector_ms != null) parts.push(`vektor ${debug.vector_ms} ms`)
  if (response.mode === 'rerank') {
    if (debug.fts_any_ms != null) parts.push(`fulltext (libovolné slovo) ${debug.fts_any_ms} ms`)
    if (debug.rerank) parts.push(`reranking ${debug.rerank.ms} ms, ${debug.rerank.calls} volání, ${debug.rerank.cached} z cache`)
  } else if (debug.fts_ms != null) {
    parts.push(`fulltext ${debug.fts_ms} ms`)
  }
  return parts.join(' · ')
}

export function CompareView({ data, filters }: Props) {
  const modes = modesOf(data)
  const tags = useMemo(() => assignTags(data, modes), [data, modes])
  const overlap = tags.size

  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">
        {overlap > 0
          ? `${overlap} úryvků se objevuje ve více sloupcích – mají stejné písmeno. `
          : 'Žádný úryvek se neobjevuje ve dvou sloupcích zároveň – metody našly úplně jiné pasáže. '}
        Skóre nejsou mezi sloupci srovnatelná (jiná stupnice), porovnávejte pořadí.
      </p>
      <div className={clsx('grid gap-4', modes.length === 4 ? 'lg:grid-cols-4' : 'lg:grid-cols-3')}>
        {modes.map((mode) => {
          const response = responseOf(data, mode)
          const gate = response.debug.rerank
          return (
            <section key={mode} className="min-w-0">
              <header className="sticky top-0 z-10 mb-2 rounded-lg border border-slate-200 border-t-4 border-t-brand-700 bg-white px-3 py-2 shadow-sm">
                <h2 className="flex items-center gap-2 font-semibold text-brand-900">
                  {MODE_INFO[mode].label}
                  <span title={MODE_INFO[mode].explain} className="cursor-help text-slate-400 hover:text-brand-500">
                    <Info className="h-4 w-4" aria-label={MODE_INFO[mode].explain} />
                  </span>
                  <span className="ml-auto text-xs font-normal text-slate-500">{response.hits.length} výsledků</span>
                </h2>
                <p className="mt-0.5 truncate text-[11px] text-slate-400" title={timing(response)}>
                  {gate ? (
                    <span className="font-medium text-leaf-700">
                      {gate.passed} z {gate.candidates} kandidátů má známku aspoň {gate.min_grade}.
                    </span>
                  ) : (
                    MODE_INFO[mode].short
                  )}
                  {timing(response) && <> · {timing(response)}</>}
                </p>
              </header>
              <ResultList response={response} compact tags={tags} emptyReason={emptyReason(mode, response, filters)} />
            </section>
          )
        })}
      </div>
    </div>
  )
}
