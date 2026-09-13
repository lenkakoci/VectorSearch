import type { Hit, Mode, View } from '../types'

export interface ModeInfo {
  label: string
  short: string
  explain: string
  scoreLabel: string
}

// Plain-language descriptions for people who have never met an embedding.
export const MODE_INFO: Record<View, ModeInfo> = {
  fts: {
    label: 'Fulltext',
    short: 'slova',
    explain:
      'Hledá úryvky, které obsahují všechna zadaná slova, i ve skloněných tvarech („vrty“ najde „vrtů“). Nezná význam: „voda blízko pod povrchem“ nenajde „mělká hladina podzemní vody“.',
    scoreLabel: 'ts_rank',
  },
  vector: {
    label: 'Sémantické',
    short: 'význam',
    explain:
      'Porovnává význam dotazu s významem textu (embeddingy). Najde i jinak formulované pasáže, ale může minout přesný kód, normu nebo číslo sondy.',
    scoreLabel: 'kosinová podobnost',
  },
  hybrid: {
    label: 'Hybridní',
    short: 'obojí',
    explain:
      'Sloučí obě pořadí metodou Reciprocal Rank Fusion. Nahoře skončí to, co našly obě metody; přesné kódy i parafráze se navzájem doplní.',
    scoreLabel: 'RRF',
  },
  rerank: {
    label: 'Reranking',
    short: 'známka',
    explain:
      'Model Gemini přečte 40 kandidátů, po dvaceti z vektoru a z fulltextu, spolu s otázkou a každému dá známku 0–3 podle toho, zda na otázku odpovídá. Úryvky pod známkou 2 jsou pod čarou: do generované odpovědi by nešly.',
    scoreLabel: 'známka 0–3',
  },
  compare: {
    label: 'Porovnat',
    short: 'vedle sebe',
    explain: 'Stejný dotaz ve všech režimech vedle sebe. Stejné písmeno = stejný úryvek nalezený více způsoby.',
    scoreLabel: '',
  },
}

export const MODES: Mode[] = ['fts', 'vector', 'hybrid']
export const COMPARE_MODES: Mode[] = ['fts', 'vector', 'hybrid', 'rerank']
export const MAX_GRADE = 3

export const DEMO_QUERIES: { query: string; why: string }[] = [
  { query: 'hladina podzemní vody', why: 'najdou všechny tři' },
  { query: 'vrty pro tepelné čerpadlo', why: 'skloňování: fulltext zvýrazní i „vrtů“' },
  { query: 'kde je voda blízko pod povrchem', why: 'jinak řečeno – silná stránka významu' },
  { query: 'ČSN 75 9010', why: 'přesný kód – silná stránka fulltextu' },
  { query: 'sonda S-2', why: 'označení sondy, často jen v příloze' },
]

export function scoreOf(hit: Hit, mode: Mode): number | null {
  if (mode === 'fts') return hit.fts_score
  if (mode === 'vector') return hit.vector_score
  if (mode === 'rerank') return hit.rerank_grade ?? null
  return hit.rrf_score
}

export function branchesOf(mode: Mode): ('fts' | 'vector')[] {
  if (mode === 'hybrid' || mode === 'rerank') return ['vector', 'fts']
  return [mode]
}

export function formatScore(value: number | null): string {
  if (value == null) return '–'
  return value.toFixed(4)
}

export function formatModeScore(hit: Hit, mode: Mode): string {
  if (mode === 'rerank') return hit.rerank_grade == null ? '–' : `${hit.rerank_grade}/${MAX_GRADE}`
  return formatScore(scoreOf(hit, mode))
}
