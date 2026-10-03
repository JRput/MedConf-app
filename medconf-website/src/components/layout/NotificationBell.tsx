// src/components/layout/NotificationBell.tsx
'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { AlertCircle, ArrowRight, Bell, Check, Clock, Info, Sparkles } from 'lucide-react'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'
import type { NotificationItem } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'

const POLL_INTERVAL_MS = 60_000 // re-fetch unread count every minute
const RECENT_LIMIT = 6

export function NotificationBell() {
  const { user } = useAuth()
  const supabase = createSupabaseClient()
  const [items, setItems] = useState<NotificationItem[]>([])
  const [unread, setUnread] = useState(0)
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState<'all' | 'unread'>('all')

  const loadRecent = async () => {
    if (!user) return
    const [recentResp, countResp] = await Promise.all([
      supabase.from('notifications').select('*').eq('user_id', user.id).order('created_at', { ascending: false }).limit(RECENT_LIMIT),
      supabase.from('notifications').select('id', { count: 'exact', head: true }).eq('user_id', user.id).is('read_at', null),
    ])
    if (recentResp.data) setItems(recentResp.data as NotificationItem[])
    if (countResp.count !== null && countResp.count !== undefined) setUnread(countResp.count)
  }

  useEffect(() => {
    if (!user) return
    loadRecent()
    const id = setInterval(loadRecent, POLL_INTERVAL_MS)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user])

  const markAsRead = async (id: string) => {
    if (!user) return
    await supabase.from('notifications').update({ read_at: new Date().toISOString() }).eq('id', id).eq('user_id', user.id)
    setItems((prev) => prev.map((n) => (n.id === id ? { ...n, read_at: new Date().toISOString() } : n)))
    setUnread((n) => Math.max(0, n - 1))
  }

  const markAllRead = async () => {
    if (!user) return
    const now = new Date().toISOString()
    await supabase.from('notifications').update({ read_at: now }).eq('user_id', user.id).is('read_at', null)
    setItems((prev) => prev.map((n) => (n.read_at ? n : { ...n, read_at: now })))
    setUnread(0)
  }

  if (!user) return null

  const visible = filter === 'unread' ? items.filter((n) => !n.read_at) : items

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`Notifications${unread > 0 ? `, ${unread} unread` : ''}`}
          className={cn(
            'relative inline-flex size-9 shrink-0 items-center justify-center rounded-md text-fg-muted',
            'transition-colors duration-150 hover:bg-surface-hover hover:text-fg',
            'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-bg focus-visible:outline-none'
          )}
        >
          <Bell className="size-[18px]" strokeWidth={1.75} aria-hidden />
          {unread > 0 && (
            <span className="absolute top-1 right-1 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-danger px-1 text-[10px] leading-none font-bold text-white">
              {unread > 9 ? '9+' : unread}
            </span>
          )}
        </button>
      </PopoverTrigger>

      <PopoverContent align="end" className="w-[360px] p-0">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <span className="text-[0.875rem] font-semibold text-fg-strong">Notifications</span>
          {unread > 0 && (
            <Button variant="ghost" size="xs" onClick={markAllRead}>
              <Check className="size-3.5" />
              Mark all read
            </Button>
          )}
        </div>

        <div className="flex gap-1 border-b border-border px-3 pt-2 pb-1">
          <FilterTab label={`All (${items.length})`} active={filter === 'all'} onClick={() => setFilter('all')} />
          <FilterTab label={`Unread (${unread})`} active={filter === 'unread'} onClick={() => setFilter('unread')} />
        </div>

        <div className="max-h-[400px] overflow-y-auto">
          {visible.length === 0 ? (
            <p className="px-4 py-8 text-center type-small text-fg-muted">
              {filter === 'unread' ? 'No unread notifications' : 'No notifications yet'}
            </p>
          ) : (
            visible.map((n) => (
              <NotificationRow
                key={n.id}
                item={n}
                onClick={() => {
                  markAsRead(n.id)
                  setOpen(false)
                }}
              />
            ))
          )}
        </div>

        <div className="border-t border-border px-4 py-2.5 text-center">
          <Link
            href="/dashboard/notifications"
            onClick={() => setOpen(false)}
            className="inline-flex items-center gap-1 type-small font-medium text-brand-text hover:underline"
          >
            View all notifications <ArrowRight className="size-3" />
          </Link>
        </div>
      </PopoverContent>
    </Popover>
  )
}

function FilterTab({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'rounded-md px-2 py-1 text-[0.75rem] font-medium transition-colors duration-150',
        active ? 'bg-surface-muted text-fg' : 'text-fg-muted hover:text-fg'
      )}
    >
      {label}
    </button>
  )
}

function extractSpecialtyFromTitle(title: string): string {
  // The cron emits titles like "3 new Cardiology events" or
  // "5 new Surgery (RCS) courses". The specialty is the slice between
  // "X new" and the trailing noun (event/conference/course/...).
  const parts = title.split(' ')
  if (parts.length < 4) return ''
  return parts.slice(2, -1).join(' ')
}

const TYPE_STYLE = {
  reminder: { icon: Clock, color: 'text-warn-text' },
  new_in_specialty: { icon: Sparkles, color: 'text-brand-text' },
  conference_change: { icon: AlertCircle, color: 'text-danger-text' },
  system: { icon: Info, color: 'text-fg-muted' },
} as const

function NotificationRow({ item, onClick }: { item: NotificationItem; onClick: () => void }) {
  const unread = !item.read_at
  const style = TYPE_STYLE[item.type] ?? TYPE_STYLE.system
  const Icon = style.icon

  // Click target depends on the notification type:
  // - reminder / conference_change: open the specific conference
  // - new_in_specialty: open the directory pre-filtered to that specialty,
  //   sorted by recently_added so the new arrivals surface at the top
  // - everything else: the full notifications list
  const href = item.conference_id
    ? `/conferences/${item.conference_id}`
    : item.type === 'new_in_specialty'
      ? `/conferences?specialty=${encodeURIComponent(extractSpecialtyFromTitle(item.title))}&sort=recently_added`
      : '/dashboard/notifications'

  return (
    <Link
      href={href}
      onClick={onClick}
      className={cn(
        'flex gap-3 border-b border-border-subtle px-4 py-3 last:border-b-0',
        'transition-colors duration-150 hover:bg-surface-hover',
        unread && 'bg-brand-subtle'
      )}
    >
      <Icon className={cn('mt-0.5 size-[18px] shrink-0', unread ? style.color : 'text-fg-subtle')} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className={cn('text-[0.8125rem] leading-snug', unread ? 'font-medium text-fg-strong' : 'text-fg')}>{item.title}</p>
        {item.body && <p className="mt-0.5 type-small text-fg-muted">{item.body}</p>}
        <p className="mt-1 type-caption text-fg-subtle">{relativeTime(item.created_at)}</p>
      </div>
      {unread && <span className="mt-2 size-2 shrink-0 rounded-full bg-brand" aria-label="Unread" />}
    </Link>
  )
}

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
