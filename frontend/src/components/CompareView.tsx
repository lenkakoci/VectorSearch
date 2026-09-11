import { useMemo } from 'react'
import { MODE_INFO, MODES } from '../lib/modes'
import type { CompareResponse, Mode, RequestFilters, SearchResponse } from '../types'
import { ResultList } from './ResultList'
import type { Tag } from './ResultCard'

const PALETTE = [
  'bg-rose-200 text-rose-900',
  'bg-emerald-200 text-emerald-900',
  'bg-sky-200 text-sky-900',
  'bg-amber-200 text-amber-900',
  'bg-violet-200 text-violet-900',
  'bg-teal-200 text-teal-900',
  'bg-orange-200 text-orange-900',
  'bg-lime-200 text-lime-900',
]

interface Props {
  data: CompareResponse
  filters: RequestFilters
}

// Chunks that appear in more than one column get the same letter and colour,
// so the overlap between the methods is visible at a glance.
function assignTags(data: CompareResponse): Map<string, Tag> {
  const seen = new Map<string, number>()
  for (const mode of MODES) {
    for (const hit of data[mode].hits) seen.set(hit.chunk_id, (seen.get(hit.chunk_id) ?? 0) + 1)
  }
  const tags = new Map<string, Tag>()
  let next = 0
  for (const mode of MODES) {
    for (const hit of data[mode].hits) {
      if ((seen.get(hit.chunk_id) ?? 0) > 1 && !tags.has(hit.chunk_id)) {
        tags.set(hit.chunk_id, { letter: String.fromCharCode(65 + (next % 26)), className: PALETTE[next % PALETTE.length] })
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
  return 'Ani jedna větev nic nenašla.'
}

function timing(response: SearchResponse): string {
  const parts: string[] = []
  if (response.debug.embed_ms != null) parts.push(`embedding ${response.debug.embed_ms} ms${response.debug.embedding_cached ? ' (cache)' : ''}`)
  if (response.debug.vector_ms != null) parts.push(`vektor ${response.debug.vector_ms} ms`)
  if (response.debug.fts_ms != null) parts.push(`fulltext ${response.debug.fts_ms} ms`)
  return parts.join(' · ')
}

export function CompareView({ data, filters }: Props) {
  const tags = useMemo(() => assignTags(data), [data])
  const overlap = tags.size

  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">
        {overlap > 0
          ? `${overlap} úryvků se objevuje ve více sloupcích – mají stejné písmeno. `
          : 'Žádný úryvek se neobjevuje ve dvou sloupcích zároveň – metody našly úplně jiné pasáže. '}
        Skóre nejsou mezi sloupci srovnatelná (jiná stupnice), porovnávejte pořadí.
      </p>
      <div className="grid gap-4 lg:grid-cols-3">
        {MODES.map((mode) => {
          const response = data[mode]
          return (
            <section key={mode} className="min-w-0">
              <header className="mb-2 rounded-lg border border-slate-200 bg-white px-3 py-2">
                <h2 className="flex items-baseline gap-2 font-semibold text-slate-800">
                  {MODE_INFO[mode].label}
                  <span className="text-xs font-normal text-slate-400">{MODE_INFO[mode].short}</span>
                  <span className="ml-auto text-xs font-normal text-slate-500">{response.hits.length} výsledků</span>
                </h2>
                <p className="mt-1 text-xs text-slate-500">{MODE_INFO[mode].explain}</p>
                {timing(response) && <p className="mt-1 text-[11px] text-slate-400">{timing(response)}</p>}
              </header>
              <ResultList response={response} compact tags={tags} emptyReason={emptyReason(mode, response, filters)} />
            </section>
          )
        })}
      </div>
    </div>
  )
}
