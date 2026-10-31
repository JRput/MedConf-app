'use client'

import { cn } from '@/lib/utils'

export function SpecialtyAlertToggle({
  checked,
  disabled,
  onChange,
  status,
  error,
}: {
  checked: boolean
  disabled?: boolean
  onChange: (next: boolean) => void
  status?: string | null
  error?: string | null
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p id="specialty-alerts-label" className="text-[0.9375rem] font-medium text-fg">
            In-app alerts for new events in my specialty
          </p>
          <p className="type-small text-fg-muted">A daily bell notification when new events match your specialty.</p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={checked}
          aria-labelledby="specialty-alerts-label"
          disabled={disabled}
          onClick={() => onChange(!checked)}
          className={cn(
            'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border border-border transition-colors',
            'outline-none focus-visible:ring-2 focus-visible:ring-ring/35 disabled:cursor-not-allowed disabled:opacity-50',
            checked ? 'bg-brand' : 'bg-surface-muted'
          )}
        >
          <span
            className={cn(
              'inline-block size-4 rounded-full bg-white shadow-xs transition-transform',
              checked ? 'translate-x-6' : 'translate-x-1'
            )}
          />
        </button>
      </div>
      {error ? (
        <p role="alert" className="type-small text-danger-text">{error}</p>
      ) : status ? (
        <p role="status" className="type-small text-fg-muted">{status}</p>
      ) : null}
    </div>
  )
}
