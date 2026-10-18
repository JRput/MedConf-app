'use client'

import { useState } from 'react'
import { PlusCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { AddInfoSection } from '@/lib/community/types'
import type { Conference, PricingTier } from '@/lib/types'
import { cn } from '@/lib/utils'
import { AddInfoDialog } from './AddInfoDialog'
import { PRESS } from './press'

/**
 * A button or inline link that owns an AddInfoDialog. Safe to drop into
 * server-rendered pages: it is the only client boundary the page needs.
 *  - variant "button": full outline button with a plus icon
 *  - variant "link":   inline text link for in-context prompts
 */
export function AddInfoTrigger({
  conference,
  tiers,
  section,
  variant = 'button',
  className,
  children,
}: {
  conference: Conference
  tiers: PricingTier[]
  section?: AddInfoSection
  variant?: 'button' | 'link'
  className?: string
  children?: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  // Mount the dialog on first use, then keep it so Radix can play the exit animation.
  const [mounted, setMounted] = useState(false)
  const show = () => {
    setMounted(true)
    setOpen(true)
  }
  return (
    <>
      {variant === 'button' ? (
        <Button type="button" variant="outline" className={cn(PRESS, 'h-11 w-full', className)} onClick={show} aria-haspopup="dialog">
          <PlusCircle aria-hidden />
          {children ?? 'Add missing info'}
        </Button>
      ) : (
        <button
          type="button"
          onClick={show}
          aria-haspopup="dialog"
          className={cn(
            PRESS,
            'inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded-sm type-small font-medium text-brand-text',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [@media(hover:hover)_and_(pointer:fine)]:hover:underline',
            className
          )}
        >
          {children ?? 'Add missing info'}
        </button>
      )}
      {mounted && <AddInfoDialog conference={conference} tiers={tiers} open={open} onOpenChange={setOpen} initialSection={section} />}
    </>
  )
}
