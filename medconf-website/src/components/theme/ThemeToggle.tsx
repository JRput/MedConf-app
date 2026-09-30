'use client'

import * as React from 'react'
import { useTheme } from 'next-themes'
import { Moon, Sun } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Two-state toggle (light <-> dark). `resolvedTheme` is used so a visitor still
 * on "system" flips to the opposite of what they are *seeing*, not to the
 * opposite of the string "system".
 *
 * Before mount we render a same-sized, inert placeholder: next-themes cannot
 * know the theme during SSR, and rendering the wrong icon then swapping is the
 * flash this is meant to avoid.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme()
  const [mounted, setMounted] = React.useState(false)
  React.useEffect(() => setMounted(true), [])

  const isDark = resolvedTheme === 'dark'

  const base = cn(
    'inline-flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-md',
    'border border-transparent text-fg-muted',
    'transition-colors duration-150',
    'hover:bg-surface-hover hover:text-fg',
    'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-bg focus-visible:outline-none',
    className
  )

  if (!mounted) {
    return <span aria-hidden className={cn(base, 'pointer-events-none opacity-0')} />
  }

  return (
    <button
      type="button"
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      className={base}
      aria-label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
      title={isDark ? 'Light theme' : 'Dark theme'}
    >
      {isDark ? <Sun className="size-[18px]" strokeWidth={1.75} /> : <Moon className="size-[18px]" strokeWidth={1.75} />}
    </button>
  )
}
