// One meaning per colour, across every tab. The palette itself is defined in
// tailwind.config.js from the colours of cgs.gov.cz:
//   brand  navy and blue: structure, actions, links, citations
//   leaf   green: relevant, verified, found by both methods
//   sand   ochre: words (full text), caution, below the gate
//   clay   salmon: errors and paid calls
//   slate  neutral grey: annex, context, everything secondary

/** Reranker grades 0-3, from a confident green down to grey. */
export const GRADE_CLASS: Record<number, string> = {
  3: 'bg-leaf-700 text-white',
  2: 'bg-leaf-200 text-leaf-900',
  1: 'bg-sand-200 text-sand-900',
  0: 'bg-slate-200 text-slate-600',
}

/** Which branch found a chunk. */
export const FOUND_CLASS = {
  words: 'bg-sand-100 text-sand-800',
  meaning: 'bg-brand-100 text-brand-800',
  both: 'bg-leaf-100 text-leaf-800',
  none: 'bg-clay-100 text-clay-800',
  annex: 'bg-slate-200 text-slate-700',
  neutral: 'bg-slate-100 text-slate-600',
}

/** Letters marking the same chunk in several comparison columns. */
export const TAG_PALETTE = [
  'bg-clay-200 text-clay-900',
  'bg-leaf-200 text-leaf-900',
  'bg-brand-200 text-brand-900',
  'bg-sand-200 text-sand-900',
  'bg-clay-300 text-clay-900',
  'bg-leaf-300 text-leaf-900',
  'bg-brand-300 text-brand-900',
  'bg-sand-300 text-sand-900',
]
