// src/app/dashboard/notifications/page.tsx
'use client'

import { useState, useEffect, useMemo } from 'react'
import Link from 'next/link'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'
import type { NotificationItem } from '@/lib/types'
import {
  Bell, Clock, Sparkles, AlertCircle, Info, Loader2, Check, ArrowRight, ChevronLeft,
} from 'lucide-react'

export default function NotificationsPage() {
  const { user } = useAuth()
  const supabase = createSupabaseClient()
  const [items, setItems] = useState<NotificationItem[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'unread'>('all')

  useEffect(() => {
    if (!user) return
    const load = async () => {
      const { data } = await supabase
        .from('notifications')
        .select('*')
        .eq('user_id', user.id)
        .order('created_at', { ascending: false })
        .limit(200)
      if (data) setItems(data as NotificationItem[])
      setLoading(false)
    }
    load()
  }, [user, supabase])

  const visible = useMemo(
    () => filter === 'unread' ? items.filter(n => !n.read_at) : items,
    [items, filter]
  )

  const unreadCount = items.filter(n => !n.read_at).length

  const markAsRead = async (id: string) => {
    if (!user) return
    await supabase
      .from('notifications')
      .update({ read_at: new Date().toISOString() })
      .eq('id', id)
      .eq('user_id', user.id)
    setItems(prev => prev.map(n => n.id === id ? { ...n, read_at: new Date().toISOString() } : n))
  }

  const markAllRead = async () => {
    if (!user || unreadCount === 0) return
    const now = new Date().toISOString()
    await supabase
      .from('notifications')
      .update({ read_at: now })
      .eq('user_id', user.id)
      .is('read_at', null)
    setItems(prev => prev.map(n => n.read_at ? n : { ...n, read_at: now }))
  }

  if (loading) {
    return (
      <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
      </div>
    )
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-grid-pattern">
      <div className="fixed inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 -z-10" />

      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-2 text-slate-400 hover:text-cyan-400 text-sm mb-6 transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          Back to dashboard
        </Link>

        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-cyan-500/20 to-teal-500/20 border border-cyan-500/30 flex items-center justify-center">
              <Bell className="w-5 h-5 text-cyan-400" />
            </div>
            <h1 className="text-3xl font-bold text-white font-display">Notifications</h1>
          </div>
          <p className="text-slate-400 ml-13">
            {items.length === 0
              ? 'You have no notifications yet.'
              : `${unreadCount} unread of ${items.length}`}
          </p>
        </div>

        {items.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="glass-card rounded-2xl overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
              <div className="flex gap-4 text-sm">
                <FilterTab label={`All (${items.length})`} active={filter === 'all'} onClick={() => setFilter('all')} />
                <FilterTab label={`Unread (${unreadCount})`} active={filter === 'unread'} onClick={() => setFilter('unread')} />
              </div>
              {unreadCount > 0 && (
                <button
                  onClick={markAllRead}
                  className="text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1"
                >
                  <Check className="w-3.5 h-3.5" />
                  Mark all as read
                </button>
              )}
            </div>

            <div>
              {visible.length === 0 ? (
                <div className="py-12 text-center text-sm text-slate-500">
                  {filter === 'unread' ? 'No unread notifications' : 'No notifications match'}
                </div>
              ) : (
                visible.map(n => (
                  <Row key={n.id} item={n} onClick={() => markAsRead(n.id)} />
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function FilterTab({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`pb-1 ${active ? 'text-white font-medium border-b-2 border-cyan-400' : 'text-slate-400 hover:text-slate-200'}`}
    >
      {label}
    </button>
  )
}

function Row({ item, onClick }: { item: NotificationItem; onClick: () => void }) {
  const unread = !item.read_at
  const style = TYPE_STYLE[item.type] ?? TYPE_STYLE.system
  const Icon = style.icon
  const href = item.conference_id ? `/conferences/${item.conference_id}` : '#'

  return (
    <Link
      href={href}
      onClick={onClick}
      className={`flex gap-4 px-5 py-4 border-b border-slate-800/60 hover:bg-slate-800/40 transition-colors ${unread ? style.bgUnread : ''}`}
    >
      <Icon className={`w-5 h-5 mt-0.5 flex-shrink-0 ${unread ? style.icon_color : 'text-slate-500'}`} />
      <div className="flex-1 min-w-0">
        <p className={`text-sm leading-tight ${unread ? 'text-white font-medium' : 'text-slate-300'}`}>
          {item.title}
        </p>
        {item.body && (
          <p className={`text-sm mt-1 ${unread ? 'text-slate-400' : 'text-slate-500'}`}>
            {item.body}
          </p>
        )}
        <p className="text-[11px] text-slate-500 mt-1.5">{absoluteTime(item.created_at)}</p>
      </div>
      {unread && <span className="w-2 h-2 rounded-full bg-cyan-400 flex-shrink-0 mt-2" aria-label="Unread" />}
    </Link>
  )
}

function EmptyState() {
  return (
    <div className="glass-card rounded-2xl p-12 text-center">
      <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-slate-800/50 flex items-center justify-center">
        <Bell className="w-8 h-8 text-slate-500" />
      </div>
      <h2 className="text-lg font-semibold text-white mb-2">No notifications yet</h2>
      <p className="text-slate-400 mb-6 max-w-md mx-auto">
        Set reminders on conferences you care about, and you&apos;ll see them here when deadlines approach.
      </p>
      <Link
        href="/conferences"
        className="inline-flex items-center gap-2 text-cyan-400 hover:text-cyan-300 text-sm font-medium"
      >
        Browse conferences <ArrowRight className="w-4 h-4" />
      </Link>
    </div>
  )
}

const TYPE_STYLE = {
  reminder: { icon: Clock, icon_color: 'text-amber-400', bgUnread: 'bg-amber-500/5' },
  new_in_specialty: { icon: Sparkles, icon_color: 'text-cyan-400', bgUnread: 'bg-cyan-500/5' },
  conference_change: { icon: AlertCircle, icon_color: 'text-rose-400', bgUnread: 'bg-rose-500/5' },
  system: { icon: Info, icon_color: 'text-slate-400', bgUnread: 'bg-slate-500/5' },
} as const

function absoluteTime(iso: string): string {
  return new Date(iso).toLocaleString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
