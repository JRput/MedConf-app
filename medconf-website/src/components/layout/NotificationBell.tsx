// src/components/layout/NotificationBell.tsx
'use client'

import { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'
import type { NotificationItem } from '@/lib/types'
import { Bell, Clock, Sparkles, AlertCircle, Info, ArrowRight } from 'lucide-react'

const POLL_INTERVAL_MS = 60_000 // re-fetch unread count every minute
const RECENT_LIMIT = 6

export function NotificationBell() {
  const { user } = useAuth()
  const supabase = createSupabaseClient()
  const [items, setItems] = useState<NotificationItem[]>([])
  const [unread, setUnread] = useState(0)
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState<'all' | 'unread'>('all')
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Fetch the most recent N notifications + a separate unread count
  const loadRecent = async () => {
    if (!user) return
    const [recentResp, countResp] = await Promise.all([
      supabase
        .from('notifications')
        .select('*')
        .eq('user_id', user.id)
        .order('created_at', { ascending: false })
        .limit(RECENT_LIMIT),
      supabase
        .from('notifications')
        .select('id', { count: 'exact', head: true })
        .eq('user_id', user.id)
        .is('read_at', null),
    ])
    if (recentResp.data) setItems(recentResp.data as NotificationItem[])
    if (countResp.count !== null && countResp.count !== undefined) setUnread(countResp.count)
  }

  useEffect(() => {
    if (!user) return
    loadRecent()
    const id = setInterval(loadRecent, POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [user])

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  const markAsRead = async (id: string) => {
    if (!user) return
    await supabase
      .from('notifications')
      .update({ read_at: new Date().toISOString() })
      .eq('id', id)
      .eq('user_id', user.id)
    setItems(prev => prev.map(n => n.id === id ? { ...n, read_at: new Date().toISOString() } : n))
    setUnread(n => Math.max(0, n - 1))
  }

  const markAllRead = async () => {
    if (!user) return
    const now = new Date().toISOString()
    await supabase
      .from('notifications')
      .update({ read_at: now })
      .eq('user_id', user.id)
      .is('read_at', null)
    setItems(prev => prev.map(n => n.read_at ? n : { ...n, read_at: now }))
    setUnread(0)
  }

  if (!user) return null

  const visible = filter === 'unread' ? items.filter(n => !n.read_at) : items

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setOpen(o => !o)}
        aria-label={`Notifications${unread > 0 ? `, ${unread} unread` : ''}`}
        className="relative flex items-center justify-center w-9 h-9 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800/50 transition-all"
      >
        <Bell className="w-5 h-5" />
        {unread > 0 && (
          <span className="absolute top-1 right-1 min-w-[16px] h-4 px-1 rounded-full bg-rose-500 text-white text-[10px] font-bold flex items-center justify-center leading-none">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-[360px] bg-slate-900 border border-slate-700 rounded-xl shadow-2xl overflow-hidden z-50">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
            <span className="text-sm font-semibold text-white">Notifications</span>
            {unread > 0 && (
              <button onClick={markAllRead} className="text-xs text-cyan-400 hover:text-cyan-300">
                Mark all as read
              </button>
            )}
          </div>

          <div className="flex gap-4 px-4 pt-2 border-b border-slate-800 text-xs">
            <button
              onClick={() => setFilter('all')}
              className={`pb-2 ${filter === 'all' ? 'text-white font-medium border-b-2 border-white' : 'text-slate-400'}`}
            >
              All ({items.length})
            </button>
            <button
              onClick={() => setFilter('unread')}
              className={`pb-2 ${filter === 'unread' ? 'text-white font-medium border-b-2 border-white' : 'text-slate-400'}`}
            >
              Unread ({unread})
            </button>
          </div>

          <div className="max-h-[420px] overflow-y-auto">
            {visible.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-slate-500">
                {filter === 'unread' ? 'No unread notifications' : 'No notifications yet'}
              </div>
            ) : (
              visible.map(n => (
                <NotificationRow key={n.id} item={n} onClick={() => { markAsRead(n.id); setOpen(false) }} />
              ))
            )}
          </div>

          <div className="px-4 py-2.5 border-t border-slate-800 text-center">
            <Link
              href="/dashboard/notifications"
              onClick={() => setOpen(false)}
              className="inline-flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-300"
            >
              View all notifications <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}

function NotificationRow({ item, onClick }: { item: NotificationItem; onClick: () => void }) {
  const unread = !item.read_at
  const style = TYPE_STYLE[item.type] ?? TYPE_STYLE.system
  const Icon = style.icon

  // If the notification has a conference, link to it; otherwise to the full list
  const href = item.conference_id ? `/conferences/${item.conference_id}` : '/dashboard/notifications'

  return (
    <Link
      href={href}
      onClick={onClick}
      className={`flex gap-3 px-4 py-3 border-b border-slate-800/60 hover:bg-slate-800/40 transition-colors ${unread ? style.bgUnread : ''}`}
    >
      <Icon className={`w-5 h-5 mt-0.5 flex-shrink-0 ${unread ? style.icon_color : 'text-slate-500'}`} />
      <div className="flex-1 min-w-0">
        <p className={`text-sm leading-tight ${unread ? 'text-white font-medium' : 'text-slate-300'}`}>
          {item.title}
        </p>
        {item.body && (
          <p className={`text-xs mt-1 ${unread ? 'text-slate-400' : 'text-slate-500'}`}>
            {item.body}
          </p>
        )}
        <p className="text-[11px] text-slate-500 mt-1.5">{relativeTime(item.created_at)}</p>
      </div>
      {unread && <span className="w-2 h-2 rounded-full bg-cyan-400 flex-shrink-0 mt-2" aria-label="Unread" />}
    </Link>
  )
}

const TYPE_STYLE = {
  reminder: {
    icon: Clock,
    icon_color: 'text-amber-400',
    bgUnread: 'bg-amber-500/5',
  },
  new_in_specialty: {
    icon: Sparkles,
    icon_color: 'text-cyan-400',
    bgUnread: 'bg-cyan-500/5',
  },
  conference_change: {
    icon: AlertCircle,
    icon_color: 'text-rose-400',
    bgUnread: 'bg-rose-500/5',
  },
  system: {
    icon: Info,
    icon_color: 'text-slate-400',
    bgUnread: 'bg-slate-500/5',
  },
} as const

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60_000)
  if (m < 1) return 'Just now'
  if (m < 60) return `${m} min ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  if (d < 7) return `${d}d ago`
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}
