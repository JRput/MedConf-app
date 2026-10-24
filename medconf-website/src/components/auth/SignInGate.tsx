'use client'

// src/components/auth/SignInGate.tsx
//
// The occasional sign-in modal. Controlled (open / onOpenChange). Motion per
// the board's emil-design-eng rules: centred transform-origin, enter
// opacity 0->1 + scale(.95->1) in 200ms on cubic-bezier(0.23,1,0.32,1), exit
// 150ms; reduced motion keeps the opacity fade only. Radix handles focus trap,
// Escape, and focus return to the element that opened it.

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { SignInActions } from './SignInPrompt'

export function SignInGate({
  open,
  onOpenChange,
  next,
  title = 'Sign in to continue',
  body = 'A free account unlocks search, fees, CPD points and abstract deadlines for every event.',
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  next?: string
  title?: string
  body?: string
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={[
          'origin-center shadow-sm',
          'duration-200 ease-[cubic-bezier(0.23,1,0.32,1)] data-[state=closed]:duration-150',
          // Reduced motion: opacity only, no scale.
          'motion-reduce:data-[state=open]:zoom-in-100 motion-reduce:data-[state=closed]:zoom-out-100',
        ].join(' ')}
      >
        <DialogHeader>
          <DialogTitle className="type-h3 leading-snug text-fg-strong">{title}</DialogTitle>
          <DialogDescription className="type-body text-fg-muted">{body}</DialogDescription>
        </DialogHeader>
        <SignInActions next={next} />
      </DialogContent>
    </Dialog>
  )
}
