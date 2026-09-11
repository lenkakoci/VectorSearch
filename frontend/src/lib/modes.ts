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
      'Hledá zadaná slova, i ve skloněných tvarech („vrty“ najde „vrtů“). Nezná význam: „voda blízko pod povrchem“ nenajde „mělká hladina podzemní vody“.',
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
  compare: {
    label: 'Porovnat',
    short: 'vedle sebe',
    explain: 'Stejný dotaz ve všech třech režimech vedle sebe. Stejné písmeno = stejný úryvek nalezený více způsoby.',
    scoreLabel: '',
  },
}

export const MODES: Mode[] = ['fts', 'vector', 'hybrid']

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
  return hit.rrf_score
}

export function branchesOf(mode: Mode): ('fts' | 'vector')[] {
  if (mode === 'hybrid') return ['vector', 'fts']
  return [mode]
}

export function formatScore(value: number | null): string {
  if (value == null) return '–'
  return value.toFixed(4)
}
