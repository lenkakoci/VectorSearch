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
