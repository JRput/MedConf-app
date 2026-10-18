'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { fieldMeta, isBlank, safeHref, type EditMap, type FieldRow } from '@/lib/community/moderation'
import { cn } from '@/lib/utils'

const TEXTAREA =
  'w-full min-w-0 rounded-md border border-border bg-surface px-3 py-2 text-base md:text-sm text-fg shadow-xs placeholder:text-fg-subtle outline-none transition-[border-color,box-shadow] duration-150 focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-ring/35'

const GRID = 'md:grid-cols-[11rem_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.2fr)]'

function show(v: unknown): string {
  if (isBlank(v)) return ''
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function ValueText({ field, value }: { field: string; value: unknown }) {
  const text = show(value)
  if (!text) return <span className="text-fg-subtle">None</span>
  const href = fieldMeta(field).kind === 'url' ? safeHref(value) : null
  if (href) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className="break-all text-brand-text underline-offset-2 hover:underline">
        {text}
      </a>
    )
  }
  return <span className="whitespace-pre-wrap break-words">{text}</span>
}

/** "User entered" · "Found on organiser site" · "Final (editable)". Disagreements sit on warn-subtle. */
export function FieldReviewTable({
  rows,
  edits,
  onEdit,
  hasEnrichment,
}: {
  rows: FieldRow[]
  edits: EditMap
  onEdit: (field: string, value: unknown) => void
  hasEnrichment: boolean
}) {
  if (rows.length === 0) {
    return <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center type-small text-fg-muted">No fields to review.</p>
  }
  return (
    <div role="table" aria-label="Field review" className="overflow-hidden rounded-lg border border-border bg-surface">
      <div role="row" className={cn('hidden items-center gap-3 border-b border-border bg-surface-muted px-4 py-2 md:grid', GRID)}>
        <span role="columnheader" className="type-mono-label text-fg-subtle">Field</span>
        <span role="columnheader" className="type-mono-label text-fg-subtle">User entered</span>
        <span role="columnheader" className="type-mono-label text-fg-subtle">Found on organiser site</span>
        <span role="columnheader" className="type-mono-label text-fg-subtle">Final</span>
      </div>
      <div className="divide-y divide-border-subtle">
        {rows.map((r) => (
          <Row key={r.field} row={r} edits={edits} onEdit={onEdit} hasEnrichment={hasEnrichment} />
        ))}
      </div>
    </div>
  )
}

function Row({ row, edits, onEdit, hasEnrichment }: { row: FieldRow; edits: EditMap; onEdit: FieldReviewTableProps['onEdit']; hasEnrichment: boolean }) {
  const meta = fieldMeta(row.field)
  const id = `final-${row.field}`
  const edited = Object.prototype.hasOwnProperty.call(edits, row.field)
  const display = edited ? edits[row.field] : row.final
  const foundUsable = !!row.found && !isBlank(row.found.value)
  const canUseFound = foundUsable && row.final === undefined && !edited

  return (
    <div
      role="row"
      className={cn('grid grid-cols-1 gap-x-3 gap-y-2 px-4 py-2.5 md:min-h-11 md:items-center', GRID, row.disagrees && 'bg-warn-subtle')}
    >
      <div role="rowheader" className="flex items-center gap-2">
        <label htmlFor={id} className="type-mono-label text-fg-muted">
          {meta.label}
        </label>
        {row.disagrees && <Badge variant="warning">Differs</Badge>}
      </div>

      <div role="cell" className="min-w-0 type-small text-fg">
        <span className="mb-0.5 block type-caption text-fg-subtle md:hidden">User entered</span>
        <ValueText field={row.field} value={row.user} />
      </div>

      <div role="cell" className="min-w-0 type-small text-fg">
        <span className="mb-0.5 block type-caption text-fg-subtle md:hidden">Found on organiser site</span>
        {row.found ? (
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <ValueText field={row.field} value={row.found.value} />
            <span className="type-caption text-fg-subtle">{row.found.method.replace(/_/g, ' ')}</span>
            {canUseFound && (
              <Button type="button" variant="outline" size="xs" onClick={() => onEdit(row.field, row.found!.value)}>
                Use
              </Button>
            )}
          </div>
        ) : (
          <span className="text-fg-subtle">{hasEnrichment ? 'Not found' : 'Not checked'}</span>
        )}
      </div>

      <div role="cell" className="min-w-0">
        <span className="mb-0.5 block type-caption text-fg-subtle md:hidden">Final</span>
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <Control id={id} field={row.field} value={display} onChange={(v) => onEdit(row.field, v)} />
          </div>
          {row.fromEnrichment && (
            <div className="flex shrink-0 flex-col items-end gap-1">
              <Badge variant="info">From organiser site</Badge>
              <Button type="button" variant="ghost" size="xs" onClick={() => onEdit(row.field, row.final)}>
                Keep
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

type FieldReviewTableProps = Parameters<typeof FieldReviewTable>[0]

function Control({ id, field, value, onChange }: { id: string; field: string; value: unknown; onChange: (v: unknown) => void }) {
  const meta = fieldMeta(field)
  const str = value === undefined || value === null ? '' : String(value)
  switch (meta.kind) {
    case 'boolean':
      return (
        <label className="flex min-h-9 cursor-pointer items-center gap-2 type-small text-fg">
          <input id={id} type="checkbox" className="size-4 cursor-pointer accent-brand" checked={value === true} onChange={(e) => onChange(e.target.checked)} />
          {value === true ? 'Yes' : 'No'}
        </label>
      )
    case 'select':
      return (
        <Select value={str || undefined} onValueChange={onChange}>
          <SelectTrigger id={id} className="w-full" size="default">
            <SelectValue placeholder="Choose" />
          </SelectTrigger>
          <SelectContent position="popper">
            {(meta.options ?? []).map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )
    case 'textarea':
      return <textarea id={id} rows={3} maxLength={2000} className={TEXTAREA} value={str} onChange={(e) => onChange(e.target.value)} />
    case 'date':
      return <Input id={id} type="date" value={str} onChange={(e) => onChange(e.target.value)} />
    case 'time':
      return <Input id={id} type="time" value={str} onChange={(e) => onChange(e.target.value)} />
    case 'number':
      return <Input id={id} inputMode="decimal" value={str} onChange={(e) => onChange(e.target.value)} />
    case 'url':
      return <Input id={id} type="url" inputMode="url" placeholder="https://" value={str} onChange={(e) => onChange(e.target.value)} />
    default:
      return <Input id={id} maxLength={200} value={str} onChange={(e) => onChange(e.target.value)} />
  }
}
