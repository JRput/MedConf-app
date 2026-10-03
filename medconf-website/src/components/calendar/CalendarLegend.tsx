import { FileClock } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * What the colours mean. Small, quiet, and only three event types plus the
 * deadline marker — a legend long enough to need reading twice is a sign the
 * grid is colour-coding too many things.
 */
export function CalendarLegend({ className }: { className?: string }) {
  return (
    <ul className={cn('flex flex-wrap items-center gap-x-3 gap-y-1.5', className)}>
      <Item className="border-type-conference-border bg-type-conference-subtle">Conference</Item>
      <Item className="border-type-course-border bg-type-course-subtle">Course</Item>
      <Item className="border-type-workshop-border bg-type-workshop-subtle">Workshop</Item>
      <li className="flex items-center gap-1.5 type-mono-label text-fg-subtle">
        <FileClock className="size-3 text-warn-text" strokeWidth={2} aria-hidden />
        Abstract deadline
      </li>
    </ul>
  )
}

function Item({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <li className="flex items-center gap-1.5 type-mono-label text-fg-subtle">
      <span className={cn('size-2.5 rounded-xs border', className)} aria-hidden />
      {children}
    </li>
  )
}
