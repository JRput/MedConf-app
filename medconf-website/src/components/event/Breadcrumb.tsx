'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, ChevronRight } from 'lucide-react'

/**
 * "Directory › {specialty} › {title}" with a back link that returns to the
 * directory's filtered view the reader came from, not a bare `/conferences`
 * reset — checked via `document.referrer` so this only ever points back
 * into our own site, never a stranger's URL.
 */
export function Breadcrumb({ specialty, title, anonymous = false }: { specialty: string | null; title: string; anonymous?: boolean }) {
  const [backHref, setBackHref] = useState('/conferences')

  useEffect(() => {
    // One-time read of a browser global (document.referrer) that isn't
    // available during SSR — there's no React state to derive this from,
    // so a mount-time effect is the correct tool here, not a smell.
    try {
      const ref = document.referrer
      if (ref && new URL(ref).origin === window.location.origin && new URL(ref).pathname.startsWith('/conferences') && !new URL(ref).pathname.match(/^\/conferences\/\d+/)) {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing from document.referrer, not derivable from props/state
        setBackHref(ref.slice(window.location.origin.length))
      }
    } catch {
      // malformed/absent referrer — keep the /conferences fallback
    }
  }, [])

  return (
    <div className="mb-5 flex items-center justify-between gap-3">
      <nav aria-label="Breadcrumb" className="hidden min-w-0 items-center gap-1.5 type-small text-fg-muted sm:flex">
        <Link href={anonymous ? '/' : '/conferences'} className="shrink-0 hover:text-fg">
          {anonymous ? 'Home' : 'Directory'}
        </Link>
        {specialty && (
          <>
            <ChevronRight className="size-3.5 shrink-0 text-fg-subtle" aria-hidden />
            {anonymous ? (
              <span className="shrink-0">{specialty}</span>
            ) : (
            <Link
              href={`/conferences?specialty=${encodeURIComponent(specialty)}`}
              className="shrink-0 hover:text-fg"
            >
              {specialty}
            </Link>
            )}
          </>
        )}
        <ChevronRight className="size-3.5 shrink-0 text-fg-subtle" aria-hidden />
        <span className="truncate text-fg-subtle" title={title}>
          {title}
        </span>
      </nav>

      <Link
        href={anonymous ? '/' : backHref}
        className="inline-flex shrink-0 items-center gap-1.5 type-small font-medium text-fg-muted transition-colors duration-150 hover:text-brand-text sm:ml-auto"
      >
        <ArrowLeft className="size-4" strokeWidth={1.75} aria-hidden />
        {anonymous ? 'Back to home' : 'Back to directory'}
      </Link>
    </div>
  )
}
