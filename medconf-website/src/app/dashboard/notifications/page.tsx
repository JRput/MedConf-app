// src/app/dashboard/notifications/page.tsx
'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { AlertCircle, Check, ChevronLeft, Clock, Info, Loader2, Sparkles } from 'lucide-react'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'
import type { NotificationItem } from '@/lib/types'
import { AccountContainer, AccountPageHeader, AccountEmptyState } from '@/components/account/AccountPageHeader'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export default function NotificationsPage() {
  const { user } = useAuth()
  const supabase = createSupabaseClient()
  const [items, setItems] = useState<NotificationItem[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'unread'>('all')

  useEffect(() => {
    if (!user) return
    supabase
      .from('notifications')
      .select('*')
      .eq('user_id', user.id)
      .order('created_at', { ascending: false })
      .limit(200)
      .then(({ data }) => {
        if (data) setItems(data as NotificationItem[])
        setLoading(false)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user])

  const unreadCount = items.filter((n) => !n.read_at).length
  const visible = useMemo(() => (filter === 'unread' ? items.filter((n) => !n.read_at) : items), [items, filter])

  const markAsRead = async (id: string) => {
    if (!user) return
    await supabase.from('notifications').update({ read_at: new Date().toISOString() }).eq('id', id).eq('user_id', user.id)
    setItems((prev) => prev.map((n) => (n.id === id ? { ...n, read_at: new Date().toISOString() } : n)))
  }

  const markAllRead = async () => {
    if (!user || unreadCount === 0) return
    const now = new Date().toISOString()
    await supabase.from('notifications').update({ read_at: now }).eq('user_id', user.id).is('read_at', null)
    setItems((prev) => prev.map((n) => (n.read_at ? n : { ...n, read_at: now })))
  }

  if (loading) {
    return (
      <AccountContainer className="flex items-center justify-center">
        <Loader2 className="size-6 animate-spin text-fg-subtle" />
      </AccountContainer>
    )
  }

  return (
    <AccountContainer className="max-w-[720px]">
      <Link href="/dashboard" className="mb-6 inline-flex items-center gap-1.5 type-small text-fg-muted hover:text-fg">
        <ChevronLeft className="size-4" />
        Back to dashboard
      </Link>

      <AccountPageHeader
        title="Notifications"
        subtitle={items.length === 0 ? 'You have no notifications yet.' : `${unreadCount} unread of ${items.length}`}
      />

      {items.length === 0 ? (
        <AccountEmptyState
          title="No notifications yet"
          description="Save events you care about and you'll see reminders and specialty alerts here."
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
            <div className="flex gap-1">
              <FilterTab label={`All (${items.length})`} active={filter === 'all'} onClick={() => setFilter('all')} />
              <FilterTab label={`Unread (${unreadCount})`} active={filter === 'unread'} onClick={() => setFilter('unread')} />
            </div>
            {unreadCount > 0 && (
              <Button variant="ghost" size="sm" onClick={markAllRead}>
                <Check className="size-3.5" />
                Mark all as read
              </Button>
            )}
          </div>

          <div>
            {visible.length === 0 ? (
              <p className="py-10 text-center type-small text-fg-muted">
                {filter === 'unread' ? 'No unread notifications' : 'No notifications match'}
              </p>
            ) : (
              visible.map((n) => <Row key={n.id} item={n} onClick={() => markAsRead(n.id)} />)
            )}
          </div>
        </div>
      )}
    </AccountContainer>
  )
}

function FilterTab({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'rounded-md px-2.5 py-1.5 text-[0.8125rem] font-medium transition-colors duration-150',
        active ? 'bg-surface-muted text-fg' : 'text-fg-muted hover:text-fg'
      )}
    >
      {label}
    </button>
  )
}

function extractSpecialtyFromTitle(title: string): string {
  // The cron emits titles like "3 new Cardiology events" — the specialty is
  // the slice between "X new" and the trailing noun (event/conference/…).
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

function Row({ item, onClick }: { item: NotificationItem; onClick: () => void }) {
  const unread = !item.read_at
  const style = TYPE_STYLE[item.type] ?? TYPE_STYLE.system
  const Icon = style.icon
  const href = item.conference_id
    ? `/conferences/${item.conference_id}`
    : item.type === 'new_in_specialty'
      ? `/conferences?specialty=${encodeURIComponent(extractSpecialtyFromTitle(item.title))}&sort=recently_added`
      : '#'

  return (
    <Link
      href={href}
      onClick={onClick}
      className={cn(
        'flex gap-3.5 border-b border-border-subtle px-4 py-3.5 last:border-b-0',
        'transition-colors duration-150 hover:bg-surface-hover',
        unread && 'bg-brand-subtle'
      )}
    >
      <Icon className={cn('mt-0.5 size-[18px] shrink-0', unread ? style.color : 'text-fg-subtle')} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className={cn('text-[0.875rem] leading-snug', unread ? 'font-medium text-fg-strong' : 'text-fg')}>{item.title}</p>
        {item.body && <p className="mt-0.5 type-small text-fg-muted">{item.body}</p>}
        <p className="mt-1 type-caption text-fg-subtle">{absoluteTime(item.created_at)}</p>
      </div>
      {unread && <span className="mt-1.5 size-2 shrink-0 rounded-full bg-brand" aria-label="Unread" />}
    </Link>
  )
}

function absoluteTime(iso: string): string {
  return new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}
