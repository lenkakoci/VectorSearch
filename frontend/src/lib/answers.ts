import type { AnswerSource, AnswerStatus, CheckResult } from '../types'

export interface StatusInfo {
  label: string
  explain: string
  badge: string
  panel: string
}

// Four states, because "nevím" has to be a first-class answer. `no_evidence`
// is the only one the model never sees: the gate closed and nothing was
// generated at all.
export const ANSWER_STATUS: Record<AnswerStatus, StatusInfo> = {
  answered: {
    label: 'Odpovězeno',
    explain: 'Každá věta má zdroj a doslovný citát, který server v citovaném úryvku opravdu našel.',
    badge: 'bg-green-600 text-white',
    panel: 'border-green-200 bg-green-50',
  },
  partial: {
    label: 'Částečně',
    explain: 'Zdroje odpovídají jen na část otázky, nebo některá věta neprošla kontrolou citací.',
    badge: 'bg-amber-500 text-white',
    panel: 'border-amber-200 bg-amber-50',
  },
  insufficient: {
    label: 'Nedostatek podkladů',
    explain: 'Nalezené úryvky na otázku neodpovídají. Model nemá z čeho odpovědět a nic si nedomýšlí.',
    badge: 'bg-slate-600 text-white',
    panel: 'border-slate-200 bg-slate-50',
  },
  no_evidence: {
    label: 'Bez podkladů',
    explain: 'Žádný nalezený úryvek nedosáhl známky relevance. Model se vůbec nevolal.',
    badge: 'bg-slate-600 text-white',
    panel: 'border-slate-200 bg-slate-50',
  },
}

export const CHECK_INFO: Record<CheckResult, string> = {
  verified: 'ověřeno',
  invalid_source: 'cituje zdroj, který v kontextu není',
  unsupported: 'bez zdroje nebo bez citátu',
  quote_not_found: 'citát se v citovaném zdroji nenašel',
  number_unsupported: 'číslo z věty ve zdrojích není',
}

// Roles a chunk can have in the context, as context_builder.py sets them.
export const ROLE_INFO: Record<string, string> = {
  nalezeno: 'Našlo vyhledávání a prošlo branou relevance.',
  kontext: 'Soused přidaný kvůli souvislosti: jeho sekce pokračuje z vybraného úryvku.',
  'pod prahem': 'Nejbližší nalezený úryvek. Na odpověď nestačil, ukazuje se pro posouzení.',
}

export const DEMO_QUESTIONS: { question: string; why: string }[] = [
  { question: 'Kolik vrtů pro tepelné čerpadlo se v Roudně navrhuje?', why: 'přímá odpověď z těla zprávy' },
  { question: 'Jak blízko pod povrchem je podzemní voda v Lednici?', why: 'jinak formulovaná otázka než text posudku' },
  { question: 'Jaká je využitelná vydatnost vrtu HV-979/3?', why: 'přesné označení vrtu' },
  { question: 'Jaké obsahy kovů byly zjištěny v zeminách z vrtů J16, J20 a J22 v Myslince?', why: 'tabulka v příloze' },
  { question: 'Jaký je radonový index pozemku v Jihlavě?', why: 'v korpusu není – ukáže bránu relevance' },
]

export function pagesOf(source: Pick<AnswerSource, 'page_from' | 'page_to'>): string {
  if (!source.page_from) return ''
  const { page_from: from, page_to: to } = source
  return to && to !== from ? `s. ${from}–${to}` : `s. ${from}`
}

export function sourceById(sources: AnswerSource[], id: number): AnswerSource | undefined {
  return sources.find((source) => source.id === id)
}

/** The element id a citation scrolls to. */
export function anchorOf(id: number): string {
  return `zdroj-${id}`
}
