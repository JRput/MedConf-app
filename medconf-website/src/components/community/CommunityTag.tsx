'use client'

import { Users } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

/** Tiny inline marker for values supplied by MedConf members rather than the organiser. */
export function CommunityTag({ className }: { className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} className={cn('inline-flex rounded-sm align-middle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring', className)}>
          <Badge variant="info">
            <Users aria-hidden />
            Community
          </Badge>
        </span>
      </TooltipTrigger>
      <TooltipContent>Added by MedConf members · reviewed by moderators</TooltipContent>
    </Tooltip>
  )
}
