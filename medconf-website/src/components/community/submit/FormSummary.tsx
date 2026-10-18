'use client'

import { Check, Circle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { SectionId, SectionStatus } from './logic'

/** Sticky desktop card: what is filled, what is still required. */
export function FormSummary({
  statuses,
  missing,
  onJump,
}: {
  statuses: SectionStatus[]
  missing: string[]
  onJump: (id: SectionId) => void
}) {
  return (
    <aside aria-label="Submission progress" className="rounded-lg border border-border bg-surface p-4">
      <p className="type-mono-label text-fg-subtle">Your submission</p>
      <ul className="mt-3 space-y-0.5">
        {statuses.map((s) => {
          const complete = s.required > 0 ? s.done === s.required : s.hasContent
          return (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onJump(s.id)}
                className={cn(
                  'flex min-h-11 w-full cursor-pointer items-center gap-2.5 rounded-md px-2 text-left type-small',
                  'transition-[background-color] duration-150 ease-out outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  '[@media(hover:hover)_and_(pointer:fine)]:hover:bg-surface-hover',
                  s.hasError ? 'text-danger-text' : complete ? 'text-fg' : 'text-fg-muted'
                )}
              >
                {complete ? (
                  <Check className="size-4 shrink-0 text-ok-text" strokeWidth={2.25} aria-hidden />
                ) : (
                  <Circle className="size-4 shrink-0 text-fg-subtle" strokeWidth={1.75} aria-hidden />
                )}
                <span className="flex-1">{s.label}</span>
                {s.required > 0 && !complete && (
                  <span className="type-caption text-fg-subtle">
                    {s.done}/{s.required}
                  </span>
                )}
              </button>
            </li>
          )
        })}
      </ul>
      <div className="mt-3 border-t border-border-subtle pt-3">
        {missing.length === 0 ? (
          <p className="type-small text-ok-text">All required details are in. Ready to send.</p>
        ) : (
          <>
            <p className="type-caption font-medium text-fg-muted">Still required</p>
            <p className="mt-1 type-small text-fg">{missing.join(', ')}</p>
          </>
        )}
      </div>
    </aside>
  )
}
