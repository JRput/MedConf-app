'use client'

// src/components/auth/GatedLink.tsx
//
// A link into a members-only page. It is a real <a href> (so it is focusable,
// Enter works, middle-click and no-JS still go to the right place, where the
// route gate sends a signed-out visitor to sign-in with `next`). With JS and
// no session, a plain click opens the SignInGate carrying `next=href` instead.
// Signed in: normal client-side navigation. Space on a link does not activate
// it natively, so it is handled here to match the "Enter/Space" contract.

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { cn } from '@/lib/utils'
import { useGate } from './GateProvider'

export function GatedLink({
  href,
  children,
  className,
  gateTitle,
  gateBody,
  ...rest
}: Omit<React.ComponentProps<typeof Link>, 'href'> & {
  href: string
  gateTitle?: string
  gateBody?: string
}) {
  const { user, openGate } = useGate()
  const router = useRouter()

  const activate = () => {
    if (user) router.push(href)
    else if (openGate) openGate(href, { title: gateTitle, body: gateBody })
    else router.push(href)
  }

  return (
    <Link
      {...rest}
      href={href}
      className={cn('cursor-pointer', className)}
      onClick={(e) => {
        rest.onClick?.(e)
        if (e.defaultPrevented) return
        // Let modified clicks (new tab, etc.) and signed-in navigation proceed natively.
        if (user || !openGate || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return
        e.preventDefault()
        activate()
      }}
      onKeyDown={(e) => {
        rest.onKeyDown?.(e)
        if (e.defaultPrevented) return
        if (e.key === ' ') {
          e.preventDefault()
          activate()
        }
      }}
    >
      {children}
    </Link>
  )
}
