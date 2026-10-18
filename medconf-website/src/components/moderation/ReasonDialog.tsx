'use client'

import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { validReason } from '@/lib/community/moderation'

const TEXTAREA =
  'w-full min-w-0 rounded-md border border-border bg-surface px-3 py-2.5 text-base md:text-sm text-fg shadow-xs placeholder:text-fg-subtle outline-none transition-[border-color,box-shadow] duration-150 focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-ring/35 aria-invalid:border-danger'

/** Asks for a reason (min 5 characters). The submitter sees it, so the copy says so. */
export function ReasonDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  destructive,
  busy,
  onConfirm,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  title: string
  description: string
  confirmLabel: string
  destructive?: boolean
  busy: boolean
  onConfirm: (reason: string) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-4 bg-surface p-5 sm:max-w-md sm:p-6">
        {/* Remounted per opening so the draft never leaks between actions. */}
        {open && <ReasonForm {...{ title, description, confirmLabel, destructive, busy, onConfirm, onCancel: () => onOpenChange(false) }} />}
      </DialogContent>
    </Dialog>
  )
}

function ReasonForm({
  title,
  description,
  confirmLabel,
  destructive,
  busy,
  onConfirm,
  onCancel,
}: {
  title: string
  description: string
  confirmLabel: string
  destructive?: boolean
  busy: boolean
  onConfirm: (r: string) => void
  onCancel: () => void
}) {
  const [reason, setReason] = useState('')
  const [touched, setTouched] = useState(false)
  const bad = touched && !validReason(reason)
  return (
    <form
      noValidate
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault()
        setTouched(true)
        if (validReason(reason)) onConfirm(reason.trim())
      }}
    >
      <DialogHeader>
        <DialogTitle className="type-h3 text-fg-strong">{title}</DialogTitle>
        <DialogDescription className="type-small text-fg-muted">{description}</DialogDescription>
      </DialogHeader>
      <div className="space-y-1.5">
        <label htmlFor="mod-reason" className="block type-caption font-medium text-fg-muted">
          Reason
        </label>
        <textarea
          id="mod-reason"
          rows={4}
          maxLength={500}
          autoFocus
          className={TEXTAREA}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          onBlur={() => setTouched(true)}
          aria-invalid={bad}
          aria-describedby={bad ? 'mod-reason-error' : undefined}
        />
        {bad && (
          <p id="mod-reason-error" role="alert" className="type-caption text-danger-text">
            Give a reason of at least 5 characters so the submitter knows what to do next.
          </p>
        )}
      </div>
      <DialogFooter className="gap-2">
        <Button type="button" variant="ghost" size="lg" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" size="lg" variant={destructive ? 'destructive' : 'default'} disabled={busy} aria-busy={busy}>
          {busy && <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />}
          {confirmLabel}
        </Button>
      </DialogFooter>
    </form>
  )
}
