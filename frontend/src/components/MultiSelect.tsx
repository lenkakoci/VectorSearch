import clsx from 'clsx'
import { ChevronDown } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

export interface Option {
  value: string
  label?: string
  count?: number
}

interface Props {
  options: Option[]
  selected: string[]
  onChange: (selected: string[]) => void
  placeholder?: string
  disabled?: boolean
}

export function MultiSelect({ options, selected, onChange, placeholder = 'vše', disabled }: Props) {
  const [open, setOpen] = useState(false)
  const [needle, setNeedle] = useState('')
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const visible = useMemo(() => {
    const lower = needle.toLowerCase()
    return options.filter((option) => (option.label ?? option.value).toLowerCase().includes(lower))
  }, [options, needle])

  const toggle = (value: string) => {
    onChange(selected.includes(value) ? selected.filter((item) => item !== value) : [...selected, value])
  }

  const summary =
    selected.length === 0
      ? placeholder
      : selected.length === 1
        ? (options.find((option) => option.value === selected[0])?.label ?? selected[0])
        : `${selected.length} vybráno`

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        className={clsx(
          'flex w-full items-center justify-between gap-2 rounded-md border bg-white px-3 py-1.5 text-left text-sm',
          disabled ? 'border-slate-200 text-slate-400' : 'border-slate-300 text-slate-700 hover:border-blue-400',
        )}
      >
        <span className="truncate">{summary}</span>
        <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" />
      </button>
      {open && (
        <div className="absolute z-20 mt-1 w-full min-w-[16rem] rounded-md border border-slate-200 bg-white shadow-lg">
          <div className="border-b border-slate-100 p-2">
            <input
              autoFocus
              value={needle}
              onChange={(event) => setNeedle(event.target.value)}
              placeholder="hledat v hodnotách…"
              className="w-full rounded border border-slate-200 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-300"
            />
          </div>
          <ul className="max-h-64 overflow-auto py-1 text-sm">
            {visible.length === 0 && <li className="px-3 py-2 text-slate-400">nic neodpovídá</li>}
            {visible.map((option) => (
              <li key={option.value}>
                <label className="flex cursor-pointer items-center gap-2 px-3 py-1 hover:bg-slate-50">
                  <input
                    type="checkbox"
                    checked={selected.includes(option.value)}
                    onChange={() => toggle(option.value)}
                    className="h-4 w-4"
                  />
                  <span className="flex-1 truncate" title={option.label ?? option.value}>
                    {option.label ?? option.value}
                  </span>
                  {option.count != null && <span className="text-xs text-slate-400">{option.count}</span>}
                </label>
              </li>
            ))}
          </ul>
          {selected.length > 0 && (
            <div className="border-t border-slate-100 p-2 text-right">
              <button type="button" onClick={() => onChange([])} className="text-xs text-blue-600 hover:underline">
                zrušit výběr
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
