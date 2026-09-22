import type { LucideIcon } from 'lucide-react'

export interface EmptyStep {
  icon: LucideIcon
  title: string
  text: string
}

/** What a tab does, in three steps, shown before the first query. */
export function EmptyState({ steps }: { steps: EmptyStep[] }) {
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {steps.map((step, index) => {
        const Icon = step.icon
        return (
          <div key={step.title} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-brand-50 text-brand-700">
                <Icon className="h-4 w-4" />
              </span>
              <span className="text-xs font-semibold text-slate-400">{index + 1}.</span>
              <h3 className="font-semibold text-brand-900">{step.title}</h3>
            </div>
            <p className="mt-2 text-sm text-slate-600">{step.text}</p>
          </div>
        )
      })}
    </div>
  )
}
