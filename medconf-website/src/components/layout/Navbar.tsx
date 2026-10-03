// src/components/layout/Navbar.tsx
'use client'

import { useAuth } from '@/hooks/useAuth'
import Link from 'next/link'
import { useState } from 'react'
import { Menu, X, Calendar, CalendarDays, Bookmark, Settings, LogOut, LayoutDashboard, Building2 } from 'lucide-react'
import { NotificationBell } from './NotificationBell'
import { ThemeToggle } from '@/components/theme/ThemeToggle'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function Navbar() {
  const { user, signOut, loading } = useAuth()
  const [isMenuOpen, setIsMenuOpen] = useState(false)

  return (
    <nav className="sticky top-0 z-40 border-b border-border bg-bg">
      <div className="mx-auto max-w-[1320px] px-4 sm:px-6">
        <div className="flex h-16 items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <div className="flex size-8 items-center justify-center rounded-md bg-brand">
              <span className="text-sm font-bold text-fg-onbrand">M</span>
            </div>
            <span className="type-h3 text-fg-strong">MedConf</span>
          </Link>

          <div className="hidden items-center gap-1 md:flex">
            <ThemeToggle />
            <NavLink href="/conferences" icon={<Calendar className="size-4" />}>
              Directory
            </NavLink>
            <NavLink href="/societies" icon={<Building2 className="size-4" />}>
              Societies
            </NavLink>
            {!loading && user ? (
              <>
                <NavLink href="/dashboard" icon={<LayoutDashboard className="size-4" />}>
                  Dashboard
                </NavLink>
                <NavLink href="/calendar" icon={<CalendarDays className="size-4" />}>
                  Calendar
                </NavLink>
                <NavLink href="/saved" icon={<Bookmark className="size-4" />}>
                  Saved
                </NavLink>
                <NavLink href="/settings" icon={<Settings className="size-4" />}>
                  Settings
                </NavLink>
                <NotificationBell />
                <Button variant="ghost" size="sm" onClick={signOut}>
                  <LogOut className="size-4" />
                  Sign out
                </Button>
              </>
            ) : !loading ? (
              <>
                <Button variant="ghost" size="sm" asChild>
                  <Link href="/auth/login">Sign in</Link>
                </Button>
                <Button size="sm" asChild>
                  <Link href="/auth/signup">Get started</Link>
                </Button>
              </>
            ) : null}
          </div>

          <button
            onClick={() => setIsMenuOpen((o) => !o)}
            className="rounded-md p-2 text-fg-muted hover:bg-surface-hover hover:text-fg md:hidden"
            aria-label={isMenuOpen ? 'Close menu' : 'Open menu'}
          >
            {isMenuOpen ? <X className="size-6" /> : <Menu className="size-6" />}
          </button>
        </div>
      </div>

      {isMenuOpen && (
        <div className="border-t border-border bg-bg md:hidden">
          <div className="space-y-1 px-4 py-4">
            <MobileNavLink href="/conferences" onClick={() => setIsMenuOpen(false)}>
              Directory
            </MobileNavLink>
            <MobileNavLink href="/societies" onClick={() => setIsMenuOpen(false)}>
              Societies
            </MobileNavLink>
            {!loading && user ? (
              <>
                <MobileNavLink href="/dashboard" onClick={() => setIsMenuOpen(false)}>
                  Dashboard
                </MobileNavLink>
                <MobileNavLink href="/calendar" onClick={() => setIsMenuOpen(false)}>
                  Calendar
                </MobileNavLink>
                <MobileNavLink href="/saved" onClick={() => setIsMenuOpen(false)}>
                  Saved
                </MobileNavLink>
                <MobileNavLink href="/settings" onClick={() => setIsMenuOpen(false)}>
                  Settings
                </MobileNavLink>
                <button
                  onClick={() => {
                    signOut()
                    setIsMenuOpen(false)
                  }}
                  className="block w-full rounded-md px-3 py-2.5 text-left text-[0.9375rem] text-danger-text hover:bg-surface-hover"
                >
                  Sign out
                </button>
              </>
            ) : !loading ? (
              <>
                <MobileNavLink href="/auth/login" onClick={() => setIsMenuOpen(false)}>
                  Sign in
                </MobileNavLink>
                <Link
                  href="/auth/signup"
                  onClick={() => setIsMenuOpen(false)}
                  className="mt-1 block rounded-md bg-brand px-3 py-2.5 text-center text-[0.9375rem] font-medium text-fg-onbrand"
                >
                  Get started
                </Link>
              </>
            ) : null}
          </div>
        </div>
      )}
    </nav>
  )
}

function NavLink({ href, children, icon }: { href: string; children: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <Link
      href={href}
      className={cn(
        'flex items-center gap-2 rounded-md px-3 py-2 text-[0.8125rem] font-medium text-fg-muted',
        'transition-colors duration-150 hover:bg-surface-hover hover:text-fg'
      )}
    >
      {icon}
      {children}
    </Link>
  )
}

function MobileNavLink({ href, children, onClick }: { href: string; children: React.ReactNode; onClick: () => void }) {
  return (
    <Link href={href} onClick={onClick} className="block rounded-md px-3 py-2.5 text-[0.9375rem] text-fg hover:bg-surface-hover">
      {children}
    </Link>
  )
}
