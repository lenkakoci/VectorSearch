import type { ReactNode } from 'react'

// The API returns ts_headline output: the verbatim chunk text with the
// matching words wrapped in <mark>. Nothing else in it is markup, and chunk
// text from a PDF can contain a literal "<", so the string is split on the
// two tags and rendered as text nodes rather than injected as HTML.
export function Highlight({ text }: { text: string }) {
  const parts = text.split(/(<mark>|<\/mark>)/)
  const nodes: ReactNode[] = []
  let inside = false
  parts.forEach((part, index) => {
    if (part === '<mark>') inside = true
    else if (part === '</mark>') inside = false
    else if (part) nodes.push(inside ? <mark key={index}>{part}</mark> : <span key={index}>{part}</span>)
  })
  return <>{nodes}</>
}

// A quote the model returned, found again in the chunk it cites. The server
// has already verified it (citation_check.py), but it verified a normalised
// form: doubled spaces, line breaks and the kind of dash may differ from what
// is on screen. The same tolerance is rebuilt here, so the sentence a citation
// points at can be shown highlighted rather than only counted.
const REGEX_ESCAPE = /[.*+?^${}()|[\]\\]/g
const DASHES = /[-‐‑‒–—―−]/g
const DASH_CLASS = '[-‐‑‒–—―−]'

function quotePattern(quote: string): string | null {
  const words = quote.trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return null
  return words.map((word) => word.replace(REGEX_ESCAPE, '\\$&').replace(DASHES, DASH_CLASS)).join('\\s+')
}

export function QuoteHighlight({ text, quotes }: { text: string; quotes: string[] }) {
  const patterns = quotes.map(quotePattern).filter((pattern): pattern is string => Boolean(pattern))
  if (patterns.length === 0) return <>{text}</>
  let regex: RegExp
  try {
    regex = new RegExp(`(${patterns.join('|')})`, 'gi')
  } catch {
    return <>{text}</>
  }
  const parts = text.split(regex)
  if (parts.length === 1) return <>{text}</>
  return (
    <>
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          <mark key={index} className="rounded bg-amber-200 px-0.5">
            {part}
          </mark>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  )
}
