'use client'

// src/components/auth/SignInGate.tsx
//
// The occasional sign-in modal. Controlled (open / onOpenChange). Motion per
// the board's emil-design-eng rules: centred transform-origin, enter
// opacity 0->1 + scale(.95->1) in 200ms on cubic-bezier(0.23,1,0.32,1), exit
// 150ms; reduced motion keeps the opacity fade only. Radix handles focus trap,
// Escape, and focus return to the element that opened it.

import { useRef } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { SignInActions } from './SignInPrompt'

export function SignInGate({
  open,
  onOpenChange,
  next,
  title = 'Unlock with a free account',
  body = 'A free account unlocks search, fees, CPD points and abstract deadlines for every event.',
  restoreFocusTo,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  next?: string
  title?: string
  body?: string
  /** Element to return focus to on close (the trigger that opened the gate). */
  restoreFocusTo?: HTMLElement | null
}) {
  const contentRef = useRef<HTMLDivElement>(null)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        ref={contentRef}
        onOpenAutoFocus={(e) => {
          // Land on the primary action, not the close button.
          e.preventDefault()
          contentRef.current?.querySelector<HTMLElement>('[data-gate-primary]')?.focus()
        }}
        onCloseAutoFocus={(e) => {
          // Return focus to whatever opened the gate, if it is still mounted.
          e.preventDefault()
          if (restoreFocusTo?.isConnected) restoreFocusTo.focus()
        }}
        className={[
          'origin-center shadow-sm',
          'duration-200 ease-[cubic-bezier(0.23,1,0.32,1)] data-[state=closed]:duration-150',
          // Reduced motion: opacity only, no scale.
          'motion-reduce:data-[state=open]:zoom-in-100 motion-reduce:data-[state=closed]:zoom-out-100',
        ].join(' ')}
      >
        <DialogHeader className="text-left">
          <DialogTitle className="type-h3 leading-snug text-fg-strong">{title}</DialogTitle>
          <DialogDescription className="type-body text-fg-muted">{body}</DialogDescription>
        </DialogHeader>
        <SignInActions next={next} />
      </DialogContent>
    </Dialog>
  )
}
