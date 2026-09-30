import { Building2, Globe, MonitorSmartphone } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Conference } from '@/lib/types'

type Format = NonNullable<Conference['event_format']>

const SPEC: Record<Format, { label: string; Icon: typeof Globe; tone: string }> = {
  online: { label: 'Online', Icon: Globe, tone: 'text-fmt-online-text' },
  in_person: { label: 'In person', Icon: Building2, tone: 'text-fmt-inperson-text' },
  hybrid: { label: 'Hybrid', Icon: MonitorSmartphone, tone: 'text-fmt-hybrid-text' },
}

/**
 * Icon + label, quiet by default. Format matters ("do I have to travel?") but
 * it is not a status — so it stays as text with a coloured icon rather than a
 * filled chip, which keeps the row's colour budget for urgency signals.
 */
export function FormatBadge({
  format,
  size = 'sm',
  showLabel = true,
  className,
}: {
  format: Conference['event_format']
  size?: 'sm' | 'md'
  showLabel?: boolean
  className?: string
}) {
  if (!format) return null
  const { label, Icon, tone } = SPEC[format]
  const px = size === 'md' ? 'size-5' : 'size-4'

  return (
    <span
      className={cn('inline-flex items-center gap-1.5 text-fg-muted', size === 'md' ? 'text-sm' : 'text-[0.8125rem]', className)}
      title={showLabel ? undefined : label}
    >
      <Icon className={cn(px, tone)} strokeWidth={1.75} aria-hidden />
      {showLabel ? label : <span className="sr-only">{label}</span>}
    </span>
  )
}
