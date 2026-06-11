// src/components/layout/Navbar.tsx
'use client'

import { useAuth } from '@/hooks/useAuth'
import Link from 'next/link'
import { useState } from 'react'
import { Menu, X, Calendar, Bookmark, Settings, LogOut, LayoutDashboard } from 'lucide-react'
import { NotificationBell } from './NotificationBell'

export function Navbar() {
  const { user, signOut, loading } = useAuth()
  const [isMenuOpen, setIsMenuOpen] = useState(false)

  return (
    <nav className="bg-slate-900 border-b border-slate-800 sticky top-0 z-50 backdrop-blur-sm bg-opacity-95">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2 group">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-400 to-teal-500 flex items-center justify-center shadow-lg shadow-cyan-500/25 group-hover:shadow-cyan-500/40 transition-shadow">
              <span className="text-white font-bold text-sm">M</span>
            </div>
            <span className="text-xl font-bold text-white tracking-tight">
              Med<span className="text-cyan-400">Conf</span>
            </span>
          </Link>

          {/* Desktop Navigation */}
          <div className="hidden md:flex items-center gap-1">
            {!loading && user ? (
              <>
                <NavLink href="/dashboard" icon={<LayoutDashboard className="w-4 h-4" />}>
                  Dashboard
                </NavLink>
                <NavLink href="/conferences" icon={<Calendar className="w-4 h-4" />}>
                  Conferences
                </NavLink>
                <NavLink href="/saved" icon={<Bookmark className="w-4 h-4" />}>
                  Saved
                </NavLink>
                <NavLink href="/settings" icon={<Settings className="w-4 h-4" />}>
                  Settings
                </NavLink>
                <NotificationBell />
                <button
                  onClick={signOut}
                  className="flex items-center gap-2 text-sm text-slate-400 hover:text-rose-400 px-4 py-2 rounded-lg hover:bg-slate-800/50 transition-all duration-200"
                >
                  <LogOut className="w-4 h-4" />
                  Sign Out
                </button>
              </>
            ) : !loading ? (
              <>
                <Link 
                  href="/auth/login" 
                  className="text-sm text-slate-300 hover:text-white px-4 py-2 rounded-lg hover:bg-slate-800/50 transition-all duration-200"
                >
                  Sign In
                </Link>
                <Link 
                  href="/auth/signup" 
                  className="text-sm bg-gradient-to-r from-cyan-500 to-teal-500 text-white px-5 py-2 rounded-lg font-medium hover:from-cyan-400 hover:to-teal-400 transition-all duration-200 shadow-lg shadow-cyan-500/25 hover:shadow-cyan-500/40"
                >
                  Get Started
                </Link>
              </>
            ) : null}
          </div>

          {/* Mobile menu button */}
          <button 
            onClick={() => setIsMenuOpen(!isMenuOpen)}
            className="md:hidden text-slate-400 hover:text-white p-2"
          >
            {isMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </div>
      </div>

      {/* Mobile menu */}
      {isMenuOpen && (
        <div className="md:hidden border-t border-slate-800 bg-slate-900/95 backdrop-blur-sm">
          <div className="px-4 py-4 space-y-2">
            {!loading && user ? (
              <>
                <MobileNavLink href="/dashboard" onClick={() => setIsMenuOpen(false)}>
                  Dashboard
                </MobileNavLink>
                <MobileNavLink href="/conferences" onClick={() => setIsMenuOpen(false)}>
                  Conferences
                </MobileNavLink>
                <MobileNavLink href="/saved" onClick={() => setIsMenuOpen(false)}>
                  Saved
                </MobileNavLink>
                <MobileNavLink href="/settings" onClick={() => setIsMenuOpen(false)}>
                  Settings
                </MobileNavLink>
                <button 
                  onClick={() => { signOut(); setIsMenuOpen(false); }}
                  className="w-full text-left text-sm text-rose-400 px-4 py-3 rounded-lg hover:bg-slate-800/50 transition-all"
                >
                  Sign Out
                </button>
              </>
            ) : !loading ? (
              <>
                <MobileNavLink href="/auth/login" onClick={() => setIsMenuOpen(false)}>
                  Sign In
                </MobileNavLink>
                <Link 
                  href="/auth/signup"
                  onClick={() => setIsMenuOpen(false)}
                  className="block text-center text-sm bg-gradient-to-r from-cyan-500 to-teal-500 text-white px-4 py-3 rounded-lg font-medium"
                >
                  Get Started
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
      className="flex items-center gap-2 text-sm text-slate-300 hover:text-white px-4 py-2 rounded-lg hover:bg-slate-800/50 transition-all duration-200"
    >
      {icon}
      {children}
    </Link>
  )
}

function MobileNavLink({ href, children, onClick }: { href: string; children: React.ReactNode; onClick: () => void }) {
  return (
    <Link 
      href={href}
      onClick={onClick}
      className="block text-sm text-slate-300 px-4 py-3 rounded-lg hover:bg-slate-800/50 transition-all"
    >
      {children}
    </Link>
  )
}


