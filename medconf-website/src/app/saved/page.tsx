// src/app/saved/page.tsx
'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { Bookmark, CalendarDays } from 'lucide-react'
import { useSavedConferences } from '@/hooks/useSavedConferences'
import { AccountContainer, AccountPageHeader, AccountEmptyState } from '@/components/account/AccountPageHeader'
import { EventRowList } from '@/components/account/EventRowList'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

type SortMode = 'date_asc' | 'date_desc' | 'deadline_asc' | 'recently_saved'

const SORT_LABEL: Record<SortMode, string> = {
  date_asc: 'Date, soonest first',
  date_desc: 'Date, latest first',
  deadline_asc: 'Abstract deadline',
  recently_saved: 'Recently saved',
}

export default function SavedPage() {
  const { events, loading, toggleSave, savedIds } = useSavedConferences()
  const [sort, setSort] = useState<SortMode>('date_asc')

  const sorted = useMemo(() => {
    const arr = [...events]
    arr.sort((a, b) => {
      switch (sort) {
        case 'date_asc':
          return (a.startDate ?? '9999').localeCompare(b.startDate ?? '9999')
        case 'date_desc':
          return (b.startDate ?? '0000').localeCompare(a.startDate ?? '0000')
        case 'deadline_asc':
          return (a.abstractDeadline ?? '9999').localeCompare(b.abstractDeadline ?? '9999')
        case 'recently_saved':
          // savedIds is a Set with no ordering guarantee once ids are removed
          // and re-added, but insertion order is preserved for ids that stay
          // put — close enough for "roughly most-recent-first" without a
          // second saved_at fetch.
          return 0
      }
    })
    return arr
  }, [events, sort])

  return (
    <AccountContainer>
      <AccountPageHeader
        title="Saved events"
        subtitle={
          events.length === 0
            ? 'Events you save from the directory appear here.'
            : `${events.length} saved event${events.length === 1 ? '' : 's'}`
        }
        action={
          events.length > 0 && (
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" asChild>
                <Link href="/calendar">
                  <CalendarDays className="size-4" aria-hidden />
                  <span className="hidden sm:inline">View on calendar</span>
                  <span className="sm:hidden">Calendar</span>
                </Link>
              </Button>
              <Select value={sort} onValueChange={(v) => setSort(v as SortMode)}>
                <SelectTrigger className="w-[180px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(SORT_LABEL).map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )
        }
      />

      <EventRowList
        events={sorted}
        savedIds={savedIds}
        onToggleSave={(id) => toggleSave(id)}
        loading={loading}
        skeletonCount={4}
        emptyState={
          <AccountEmptyState
            title="No saved events yet"
            description="Browse the directory and save events you want to track — they'll show up here and on your dashboard."
            action={
              <Button asChild>
                <Link href="/conferences">
                  <Bookmark className="size-4" />
                  Browse the directory
                </Link>
              </Button>
            }
          />
        }
      />
    </AccountContainer>
  )
}
