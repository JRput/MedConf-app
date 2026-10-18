'use client'

import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'

/**
 * Confirms publishing an organiser link the safety check has not cleared.
 * Sending `approve_unchecked: true` is only ever done after this dialog.
 */
export function UncheckedConfirm({
  open,
  onOpenChange,
  reason,
  verb,
  busy,
  onConfirm,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  reason: string | undefined
  /** "Approve" or "Merge". */
  verb: string
  busy: boolean
  onConfirm: () => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-4 bg-surface p-5 sm:max-w-md sm:p-6">
        <DialogHeader>
          <DialogTitle className="type-h3 text-fg-strong">{verb} an unchecked link?</DialogTitle>
          <DialogDescription className="type-small text-fg-muted">
            {reason ? `${reason} ` : ''}This organiser link has not been safety-checked yet. The next automatic check runs within 6 hours. {verb === 'Merge' ? 'Merging' : 'Approving'} now
            publishes it unchecked.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2">
          <Button type="button" variant="ghost" size="lg" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button type="button" size="lg" variant="destructive" disabled={busy} aria-busy={busy} onClick={onConfirm}>
            {busy && <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />}
            {verb} anyway
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
