'use client'

import { useState } from 'react'
import { Loader2, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { AuthError } from '@/components/auth/AuthCard'
import { DELETE_CONFIRM_WORD, canConfirmDelete } from './actions'

export function DeleteAccountSection({
  onConfirm,
  error,
  deleting,
}: {
  onConfirm: () => void
  error?: string | null
  deleting?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')

  return (
    <div className="space-y-3 rounded-lg border border-danger-border bg-surface p-5">
      <div>
        <p className="text-[0.9375rem] font-medium text-danger-text">Delete account</p>
        <p className="type-small mt-1 text-fg-muted">
          This permanently deletes your profile, saved events, reminders, notifications and preferences. Community contributions
          that were already published are kept, without your name. This cannot be undone.
        </p>
      </div>

      {!open ? (
        <Button variant="outline" className="text-danger-text" onClick={() => setOpen(true)}>
          <Trash2 className="size-4" />
          Delete my account
        </Button>
      ) : (
        <div className="space-y-3">
          <label htmlFor="delete-confirm" className="type-small block text-fg">
            Type <span className="font-mono font-semibold">{DELETE_CONFIRM_WORD}</span> to confirm
          </label>
          <Input
            id="delete-confirm"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            autoComplete="off"
            disabled={deleting}
          />
          {error ? <AuthError message={error} /> : null}
          <div className="flex flex-wrap gap-2">
            <Button variant="destructive" disabled={!canConfirmDelete(typed) || deleting} onClick={onConfirm}>
              {deleting ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
              {deleting ? 'Deleting…' : 'Permanently delete my account'}
            </Button>
            <Button
              variant="ghost"
              disabled={deleting}
              onClick={() => {
                setOpen(false)
                setTyped('')
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
