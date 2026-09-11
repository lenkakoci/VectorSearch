import { Search } from 'lucide-react'
import type { FormEvent } from 'react'
import { DEMO_QUERIES } from '../lib/modes'

interface Props {
  query: string
  loading: boolean
  onChange: (query: string) => void
  onSubmit: (query: string) => void
}

export function SearchBar({ query, loading, onChange, onSubmit }: Props) {
  const submit = (event: FormEvent) => {
    event.preventDefault()
    onSubmit(query)
  }
  return (
    <div className="space-y-2">
      <form onSubmit={submit} className="flex gap-2">
        <label className="relative flex-1">
          <span className="sr-only">Co hledáte?</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
          <input
            autoFocus
            value={query}
            onChange={(event) => onChange(event.target.value)}
            placeholder="Co hledáte? Např. hladina podzemní vody"
            className="w-full rounded-lg border border-slate-300 bg-white py-3 pl-10 pr-3 text-lg shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
        </label>
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="rounded-lg bg-blue-600 px-5 py-3 font-medium text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {loading ? 'Hledám…' : 'Hledat'}
        </button>
      </form>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-slate-500">Zkuste:</span>
        {DEMO_QUERIES.map((demo) => (
          <button
            key={demo.query}
            type="button"
            title={demo.why}
            onClick={() => {
              onChange(demo.query)
              onSubmit(demo.query)
            }}
            className="rounded-full border border-slate-300 bg-white px-3 py-1 text-slate-700 hover:border-blue-400 hover:text-blue-700"
          >
            {demo.query}
          </button>
        ))}
        <span className="text-xs text-slate-400">
          Tip: <code>autor:Poul</code>, <code>"přesná fráze"</code>, <code>-slovo</code>, <code>a or b</code>
        </span>
      </div>
    </div>
  )
}
