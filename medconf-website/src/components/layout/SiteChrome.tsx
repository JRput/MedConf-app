'use client'

import { usePathname } from 'next/navigation'

/**
 * Hides the legacy dark-slate Navbar/Footer on routes that have already moved
 * to the new token system, so a half-migrated site never shows two palettes
 * stacked on top of each other.
 *
 * W1 only has /design on this list. As W2–W6 migrate pages, routes come OFF
 * this list (they get the redesigned chrome instead) and once the list is empty
 * this component is deleted.
 */
const CHROMELESS = ['/design']

export function SiteChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  if (CHROMELESS.some((p) => pathname === p || pathname.startsWith(`${p}/`))) return null
  return <>{children}</>
}
