import Link from 'next/link'
import { ArrowLeft, CalendarX } from 'lucide-react'

export default function NotFound() {
  return (
    <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-bg px-4">
      <div className="text-center">
        <div className="mx-auto mb-4 flex size-14 items-center justify-center rounded-full border border-danger-border bg-danger-subtle">
          <CalendarX className="size-6 text-danger-text" strokeWidth={1.75} aria-hidden />
        </div>
        <h1 className="type-h2 mb-2 text-fg-strong">Event not found</h1>
        <p className="type-body mb-6 text-fg-muted">
          This event may have been removed, archived, or the link is incorrect.
        </p>
        <Link
          href="/conferences"
          className="inline-flex items-center gap-2 type-small font-medium text-brand-text hover:underline"
        >
          <ArrowLeft className="size-4" aria-hidden />
          Back to directory
        </Link>
      </div>
    </div>
  )
}
