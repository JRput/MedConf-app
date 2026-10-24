// src/components/home/HomeSection.tsx
//
// One homepage band. Every section uses this so the rhythm is identical: a
// thin rule, a mono eyebrow heading on the left, an optional "see all" link on
// the right, then the content (a max-w-5xl column). The "see all" link always
// points at a members-only page, so it is a GatedLink. The rule is the ONLY
// divider on the page — no cards-within-cards, no tinted backgrounds.

import { ArrowRight } from 'lucide-react'
import { GatedLink } from '@/components/auth/GatedLink'

export function HomeSection({
  title,
  note,
  link,
  children,
}: {
  title: string
  /** Honest, countable context for the heading — e.g. "6 within 14 days". */
  note?: string
  link?: { href: string; label: string }
  children: React.ReactNode
}) {
  return (
    <section className="border-t border-border py-20 sm:py-24">
      <div className="max-w-5xl">
        <div className="mb-6 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 className="type-mono-label text-fg-subtle">{title}</h2>
            {note && <p className="text-[0.8125rem] text-fg-muted">{note}</p>}
          </div>
          {link && (
            <GatedLink
              href={link.href}
              className="group inline-flex min-h-11 items-center gap-1.5 rounded-sm text-[0.8125rem] font-medium text-brand-text focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none focus-visible:underline [@media(hover:hover)_and_(pointer:fine)]:hover:underline"
            >
              {link.label}
              <ArrowRight className="size-3.5" aria-hidden />
            </GatedLink>
          )}
        </div>
        {children}
      </div>
    </section>
  )
}
