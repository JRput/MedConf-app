import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * The one page-title treatment every account surface (/dashboard, /saved,
 * /settings) shares — plain type-h1 + a muted one-line subtitle, no icon
 * tile, no gradient badge. Matches the directory's restraint rather than the
 * old dashboard/saved/settings pages' per-page icon-chip header pattern.
 */
export function AccountPageHeader({
  title,
  subtitle,
  action,
  className,
}: {
  title: string
  subtitle?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('mb-6 flex items-start justify-between gap-4 sm:mb-8', className)}>
      <div>
        <h1 className="type-h1 text-fg-strong">{title}</h1>
        {subtitle && <p className="mt-1.5 type-body text-fg-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}

/** Shared max-width/padding wrapper for the account surfaces. */
export function AccountContainer({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('mx-auto max-w-[1180px] px-4 py-8 sm:px-6', className)}>{children}</div>
}

/** A titled block of rows/cards within an account page — section title + optional "see all" link slot. */
export function AccountSection({
  title,
  action,
  children,
  className,
}: {
  title: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={className}>
      <div className="mb-3 flex items-end justify-between gap-3">
        <h2 className="type-h3 text-fg-strong">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

/** Quiet empty-state block reused across dashboard/saved sections. */
export function AccountEmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-surface-muted px-6 py-8 text-center">
      <p className="type-h3 text-fg">{title}</p>
      <p className="mt-1.5 type-small text-fg-muted">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
