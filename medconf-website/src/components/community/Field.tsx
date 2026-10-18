import { cn } from '@/lib/utils'

/** Label + control + inline error/hint. The control must set id, aria-invalid and aria-describedby via `fieldIds`. */
export function fieldIds(id: string) {
  return { error: `${id}-error`, hint: `${id}-hint` }
}

export function Field({
  id,
  label,
  optional,
  hint,
  error,
  className,
  children,
}: {
  id: string
  label: string
  optional?: boolean
  hint?: string
  error?: string | null
  className?: string
  children: React.ReactNode
}) {
  const ids = fieldIds(id)
  return (
    <div className={cn('space-y-1.5', className)}>
      <label htmlFor={id} className="block type-caption font-medium text-fg-muted">
        {label}
        {optional && <span className="ml-1 font-normal text-fg-subtle">(optional)</span>}
      </label>
      {children}
      {hint && !error && (
        <p id={ids.hint} className="type-caption text-fg-subtle">
          {hint}
        </p>
      )}
      {error && (
        <p id={ids.error} role="alert" className="type-caption text-danger-text">
          {error}
        </p>
      )}
    </div>
  )
}

/** aria-describedby value matching what <Field> renders. */
export function describedBy(id: string, error?: string | null, hint?: string) {
  if (error) return fieldIds(id).error
  if (hint) return fieldIds(id).hint
  return undefined
}
