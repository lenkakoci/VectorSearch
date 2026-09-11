import { useEffect, useState } from 'react'
import { api } from '../services/api'
import type { DocumentDetail } from '../types'

interface Props {
  documentId: string
}

function asList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : []
}

function asExtra(value: unknown): { key: string; value: string }[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item): item is { key: string; value: string } => typeof item === 'object' && item !== null && 'key' in item)
    .map((item) => ({ key: String(item.key), value: String(item.value) }))
}

export function DocumentInfo({ documentId }: Props) {
  const [doc, setDoc] = useState<DocumentDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .document(documentId)
      .then((data) => !cancelled && setDoc(data))
      .catch((err: Error) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [documentId])

  if (error) return <p className="text-xs text-red-600">{error}</p>
  if (!doc) return <p className="text-xs text-slate-400">načítám…</p>

  const extraction = doc.extraction
  const facts: [string, unknown][] = [
    ['Typ průzkumu', doc.report_type],
    ['Lokalita', doc.locality],
    ['Obec', extraction.municipality],
    ['Katastrální území', extraction.cadastral_area],
    ['Autor', doc.author],
    ['Organizace', extraction.author_organization],
    ['Objednatel', doc.client],
    ['Datum', doc.report_date],
    ['Zdroj', doc.source_file],
    ['Chunků', doc.chunks],
  ]
  const findings = asList(extraction.key_findings)
  const recommendations = asList(extraction.recommendations)
  const extra = asExtra(extraction.extra_fields)

  return (
    <div className="space-y-3 rounded-md bg-slate-50 p-3 text-xs">
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        {facts
          .filter(([, value]) => value != null && value !== '')
          .map(([label, value]) => (
            <div key={label} className="contents">
              <dt className="text-slate-500">{label}</dt>
              <dd className="text-slate-800">{String(value)}</dd>
            </div>
          ))}
      </dl>
      {doc.summary && (
        <div>
          <h4 className="font-semibold text-slate-600">Shrnutí</h4>
          <p className="text-slate-700">{doc.summary}</p>
        </div>
      )}
      {findings.length > 0 && (
        <div>
          <h4 className="font-semibold text-slate-600">Klíčová zjištění</h4>
          <ul className="list-disc space-y-0.5 pl-4 text-slate-700">
            {findings.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {recommendations.length > 0 && (
        <div>
          <h4 className="font-semibold text-slate-600">Doporučení</h4>
          <ul className="list-disc space-y-0.5 pl-4 text-slate-700">
            {recommendations.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {extra.length > 0 && (
        <div>
          <h4 className="font-semibold text-slate-600">Další extrahovaná pole</h4>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
            {extra.map((item) => (
              <div key={item.key} className="contents">
                <dt className="font-mono text-slate-500">{item.key}</dt>
                <dd className="text-slate-700">{item.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  )
}
