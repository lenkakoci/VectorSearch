import clsx from 'clsx'
import type { ReactNode } from 'react'

// The settings behind the "Nastavení" and "Pokročilé" buttons. They change
// cost or ranking, not what is asked, so they stay out of sight until wanted.

const SELECT = 'rounded-md border border-slate-300 bg-white px-2 py-1 text-slate-700 focus:border-brand-500 focus:outline-none'

function Field({ label, hint, children }: { label: string; hint: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-slate-700">{label}</span>
      {children}
      <span className="text-xs text-slate-500">{hint}</span>
    </label>
  )
}

function Check({ label, hint, checked, onChange }: { label: string; hint: string; checked: boolean; onChange: (on: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-start gap-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 h-4 w-4 accent-brand-700"
      />
      <span>
        <span className="font-medium text-slate-700">{label}</span>
        <span className="block text-xs text-slate-500">{hint}</span>
      </span>
    </label>
  )
}

function Select({ value, values, onChange }: { value: number; values: number[]; onChange: (value: number) => void }) {
  return (
    <select value={value} onChange={(event) => onChange(Number(event.target.value))} className={clsx(SELECT, 'w-24')}>
      {values.map((item) => (
        <option key={item} value={item}>
          {item}
        </option>
      ))}
    </select>
  )
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="mb-3 font-semibold text-slate-700">{title}</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{children}</div>
    </div>
  )
}

interface SearchProps {
  limit: number
  onLimit: (value: number) => void
  rerank: boolean
  onRerank: (on: boolean) => void
  compare: boolean
}

export function SearchOptions({ limit, onLimit, rerank, onRerank, compare }: SearchProps) {
  return (
    <Panel title="Nastavení vyhledávání">
      <Field label="Výsledků na režim" hint="Kolik úryvků ukázat v každém sloupci.">
        <Select value={limit} values={[3, 5, 10, 20]} onChange={onLimit} />
      </Field>
      {compare && (
        <Check
          label="Přidat sloupec s rerankingem"
          hint="Gemini ohodnotí 40 kandidátů. Stojí jedno až dvě volání API na dotaz."
          checked={rerank}
          onChange={onRerank}
        />
      )}
    </Panel>
  )
}

interface AskProps {
  maxSources: number
  onMaxSources: (value: number) => void
  minGrade: number
  onMinGrade: (value: number) => void
  neighbours: boolean
  onNeighbours: (on: boolean) => void
  fresh: boolean
  onFresh: (on: boolean) => void
}

export function AskOptions(props: AskProps) {
  return (
    <Panel title="Pokročilé nastavení odpovědi">
      <Field label="Zdrojů nejvýš" hint="Tolik úryvků půjde modelu jako podklad.">
        <Select value={props.maxSources} values={[4, 6, 8, 12]} onChange={props.onMaxSources} />
      </Field>
      <Field label="Známka aspoň" hint="Úryvek s nižší známkou od rerankeru se do odpovědi nedostane.">
        <Select value={props.minGrade} values={[1, 2, 3]} onChange={props.onMinGrade} />
      </Field>
      <Check
        label="Přidat sousedy"
        hint="Sousední úryvek tam, kde je sekce rozdělená do víc oken."
        checked={props.neighbours}
        onChange={props.onNeighbours}
      />
      <Check
        label="Nová odpověď"
        hint="Jinak se stejná otázka vrátí z cache. Zaškrtnutím se spočítá znovu a zaplatí."
        checked={props.fresh}
        onChange={props.onFresh}
      />
    </Panel>
  )
}

interface ToggleButtonProps {
  icon: ReactNode
  label: string
  open: boolean
  count?: number
  onClick: () => void
}

/** A toolbar button that opens a panel below the toolbar. */
export function ToggleButton({ icon, label, open, count, onClick }: ToggleButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={open}
      className={clsx(
        'flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm transition',
        open ? 'border-brand-700 bg-brand-50 text-brand-800' : 'border-slate-300 bg-white text-slate-700 hover:border-brand-400',
      )}
    >
      {icon}
      {label}
      {count != null && count > 0 && <span className="rounded-full bg-brand-700 px-1.5 text-xs text-white">{count}</span>}
    </button>
  )
}
