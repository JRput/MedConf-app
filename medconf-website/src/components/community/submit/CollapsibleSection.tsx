'use client'

import { Check, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { SectionStatus } from './logic'

/**
 * One collapsible block of the submit form. The body stays mounted (so field
 * state and aria wiring survive) but is `inert` while closed. Expand is a
 * 200 ms ease-out grid-rows + opacity transition; reduced motion keeps the
 * opacity fade and drops the movement.
 */
export function CollapsibleSection({
  id,
  index,
  status,
  open,
  onToggle,
  children,
}: {
  id: string
  index: number
  status: SectionStatus
  open: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  const complete = status.required > 0 ? status.done === status.required : status.hasContent
  const summary =
    status.required > 0
      ? complete
        ? 'Done'
        : `${status.done} of ${status.required} required`
      : status.hasContent
        ? 'Added'
        : 'Optional'

  return (
    <section
      id={`sec-${id}`}
      className={cn(
        'scroll-mt-24 rounded-lg border bg-surface',
        status.hasError ? 'border-danger-border' : 'border-border'
      )}
    >
      <h2 className="m-0">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-controls={`sec-${id}-body`}
          id={`sec-${id}-head`}
          className={cn(
            'flex min-h-14 w-full cursor-pointer items-center gap-3 rounded-lg px-4 py-3 text-left sm:px-5',
            'transition-[background-color] duration-150 ease-out',
            'outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-bg',
            '[@media(hover:hover)_and_(pointer:fine)]:hover:bg-surface-hover'
          )}
        >
          <span
            aria-hidden
            className={cn(
              'flex size-7 shrink-0 items-center justify-center rounded-full border type-caption font-medium',
              complete ? 'border-ok-border bg-ok-subtle text-ok-text' : 'border-border bg-surface-muted text-fg-muted'
            )}
          >
            {complete ? <Check className="size-4" strokeWidth={2.25} /> : index}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block type-h3 text-fg-strong">{status.label}</span>
          </span>
          <span className={cn('type-caption', status.hasError ? 'text-danger-text' : 'text-fg-subtle')}>
            {status.hasError ? 'Needs attention' : summary}
          </span>
          <ChevronDown
            aria-hidden
            className={cn(
              'size-4 shrink-0 text-fg-subtle transition-[transform] duration-200 ease-out motion-reduce:transition-none',
              open && 'rotate-180'
            )}
          />
        </button>
      </h2>
      <div
        id={`sec-${id}-body`}
        role="region"
        aria-labelledby={`sec-${id}-head`}
        inert={!open}
        className={cn(
          'grid transition-[grid-template-rows,opacity] duration-200 ease-[cubic-bezier(0.23,1,0.32,1)] motion-reduce:transition-[opacity]',
          open ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
        )}
      >
        <div className="overflow-hidden">
          <div className="space-y-4 px-4 pb-5 pt-1 sm:px-5">{children}</div>
        </div>
      </div>
    </section>
  )
}
