// src/components/home/HomeSection.tsx
//
// One homepage band. Every section on the page uses this so the rhythm is
// identical: a thin rule, a mono eyebrow heading on the left, an optional
// "see all" link on the right, then the content. The rule is the ONLY divider
// on the page — no cards-within-cards, no tinted section backgrounds.

import Link from 'next/link'
import { ArrowRight } from 'lucide-react'

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
    <section className="border-t border-border py-10 sm:py-12">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="type-mono-label text-fg-subtle">{title}</h2>
          {note && <p className="text-[0.8125rem] text-fg-muted">{note}</p>}
        </div>
        {link && (
          <Link
            href={link.href}
            className="group inline-flex items-center gap-1.5 text-[0.8125rem] font-medium text-brand-text hover:underline"
          >
            {link.label}
            <ArrowRight className="size-3.5 transition-transform duration-150 group-hover:translate-x-0.5" aria-hidden />
          </Link>
        )}
      </div>
      {children}
    </section>
  )
}
