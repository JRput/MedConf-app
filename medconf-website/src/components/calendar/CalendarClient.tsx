'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Bookmark, CalendarRange, Compass } from 'lucide-react'
import { toast } from 'sonner'
import { addMonths, eventsInMonth, monthLabel, todayIso, toIso } from '@/lib/calendar'
import { downloadIcsFeed, icsFeedCount } from '@/lib/ics'
import type { DirectoryEvent } from '@/lib/directory'
import { useSavedConferences } from '@/hooks/useSavedConferences'
import { AccountEmptyState } from '@/components/account/AccountPageHeader'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { CalendarHeader } from './CalendarHeader'
import { CalendarLegend } from './CalendarLegend'
import { MonthGrid } from './MonthGrid'
import { AgendaView } from './AgendaView'
import { WeekStrip } from './WeekStrip'
import { EventPanelHost } from './EventPanel'
import { SM_QUERY, useMediaQuery } from './useMediaQuery'
import { calendarUrl, parseCalendarUrl, type CalendarView } from './view'
import { useLocale } from './useLocale'

/**
 * /calendar — the signed-in user's saved events, on a month grid or as an
 * agenda.
 *
 * There is no "add to calendar" concept inside the product: saving an event
 * anywhere (a directory row, the detail page, the homepage) is what puts it
 * here. So this page owns no writes except the unsave in the side panel, and
 * reads through the same `useSavedConferences` hook /saved and /dashboard
 * use — one source of truth for what "saved" means.
 */
export function CalendarClient() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const locale = useLocale()
  const { events, loading, toggleSave, savedIds } = useSavedConferences()

  const { view, year, month } = useMemo(
    () => parseCalendarUrl(new URLSearchParams(searchParams.toString())),
    [searchParams]
  )

  // The panel needs to know HOW it was opened: from a chip (the event leads)
  // or from a deadline marker (the deadline leads). Carrying that alongside
  // the event is simpler than a second piece of state that could drift out of
  // sync with it.
  const [selected, setSelected] = useState<{ event: DirectoryEvent; viaDeadline: boolean } | null>(null)
  const selectEvent = useCallback((event: DirectoryEvent) => setSelected({ event, viaDeadline: false }), [])
  const selectDeadline = useCallback((event: DirectoryEvent) => setSelected({ event, viaDeadline: true }), [])
  // Phones get the week strip by default; this is the opt-in to the real grid.
  const [gridOnPhone, setGridOnPhone] = useState(false)
  const [weekAnchor, setWeekAnchor] = useState(() => todayIso())
  const isWide = useMediaQuery(SM_QUERY)

  const navigate = useCallback(
    (next: { view?: CalendarView; year?: number; month?: number }) => {
      // `push`, not `replace`, so browser back steps through the months and
      // views the user actually visited — the brief's deep-link requirement.
      router.push(calendarUrl({ view, year, month, ...next }), { scroll: false })
    },
    [router, view, year, month]
  )

  const goMonth = useCallback(
    (delta: number) => {
      const next = addMonths(year, month, delta)
      navigate({ view: 'month', ...next })
      // Keep the phone strip in step with the month being paged.
      setWeekAnchor(toIso(next.year, next.month, 1))
    },
    [navigate, year, month]
  )

  const goToday = useCallback(() => {
    const today = todayIso()
    navigate({ view: 'month', year: Number(today.slice(0, 4)), month: Number(today.slice(5, 7)) })
    setWeekAnchor(today)
  }, [navigate])

  // Keyboard: ← / → months, T today, Esc closes the panel.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const target = e.target as HTMLElement | null
      // Never steal a keystroke from a field, or from a dialog that has its
      // own Esc handling.
      if (target?.closest('input, textarea, select, [contenteditable="true"], [role="dialog"]')) return

      if (e.key === 'Escape') {
        if (selected) {
          e.preventDefault()
          setSelected(null)
        }
        return
      }
      if (view !== 'month') return
      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        goMonth(-1)
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        goMonth(1)
      } else if (e.key === 't' || e.key === 'T') {
        e.preventDefault()
        goToday()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [goMonth, goToday, selected, view])

  const monthCount = useMemo(() => eventsInMonth(events, year, month).length, [events, year, month])

  /**
   * Optimistic unsave with an undo. `toggleSave` flips the shared saved set,
   * so the event vanishes from the grid, /saved and the dashboard at once;
   * undo is the same call again.
   */
  const handleUnsave = useCallback(
    (event: DirectoryEvent) => {
      setSelected(null)
      toggleSave(event.id)
      toast.success(`Removed "${truncate(event.name)}"`, {
        action: { label: 'Undo', onClick: () => toggleSave(event.id) },
      })
    },
    [toggleSave]
  )

  const handleExportAll = useCallback(() => {
    const count = icsFeedCount(events)
    if (count === 0) {
      toast.error('Nothing to export yet', { description: 'Save some dated events first.' })
      return
    }
    downloadIcsFeed(events)
    toast.success(`Exported ${count} event${count === 1 ? '' : 's'}`, {
      description: 'Open the .ics file to import them into your calendar.',
    })
  }, [events])

  if (loading) {
    return (
      <div className="mx-auto max-w-[1320px] px-4 py-8 sm:px-6">
        <Skeleton className="h-9 w-56" />
        <Skeleton className="mt-3 h-4 w-40" />
        <Skeleton className="mt-6 h-[28rem] w-full rounded-lg" />
      </div>
    )
  }

  // Nothing saved at all — a different problem from "nothing in this month",
  // and it deserves a route out rather than an empty grid.
  if (events.length === 0) {
    return (
      <div className="mx-auto max-w-[760px] px-4 py-12 sm:px-6">
        <AccountEmptyState
          title="Your calendar is empty"
          description="Save an event anywhere on MedConf and it lands here automatically — there is nothing else to add. Multi-day congresses show as bars across the month, and abstract deadlines get their own marker."
          action={
            <div className="flex flex-wrap items-center justify-center gap-2">
              <Button asChild>
                <Link href="/conferences">
                  <Bookmark className="size-4" aria-hidden />
                  Browse the directory
                </Link>
              </Button>
              <Button variant="outline" asChild>
                <Link href="/dashboard">
                  <Compass className="size-4" aria-hidden />
                  This month in your specialty
                </Link>
              </Button>
            </div>
          }
        />
      </div>
    )
  }

  const showWeekStrip = view === 'month' && !isWide && !gridOnPhone

  return (
    <div className="mx-auto max-w-[1320px] px-4 py-8 sm:px-6">
      <CalendarHeader
        year={year}
        month={month}
        view={view}
        monthCount={monthCount}
        totalCount={events.length}
        showGridOnPhone={gridOnPhone}
        onToggleGridOnPhone={() => setGridOnPhone((v) => !v)}
        onPrev={() => goMonth(-1)}
        onNext={() => goMonth(1)}
        onToday={goToday}
        onViewChange={(next) => navigate({ view: next })}
        onExportAll={handleExportAll}
      />

      <div className="flex gap-6">
        <div className="min-w-0 flex-1">
          {view === 'agenda' ? (
            <AgendaView
              events={events}
              savedIds={savedIds}
              onToggleSave={(id) => toggleSave(id)}
              emptyState={
                <AccountEmptyState
                  title="Nothing upcoming"
                  description="Every event you have saved has already finished. Browse the directory to find the next one."
                  action={
                    <Button variant="outline" size="sm" asChild>
                      <Link href="/conferences">Browse the directory</Link>
                    </Button>
                  }
                />
              }
            />
          ) : showWeekStrip ? (
            <WeekStrip
              anchor={weekAnchor}
              events={events}
              savedIds={savedIds}
              onToggleSave={(id) => toggleSave(id)}
              onAnchorChange={setWeekAnchor}
            />
          ) : (
            <>
              <MonthGrid
                year={year}
                month={month}
                events={events}
                selectedId={selected?.event.id ?? null}
                onSelect={selectEvent}
                onSelectDeadline={selectDeadline}
                maxLanes={3}
              />
              {monthCount === 0 && (
                <p className="mt-3 text-center type-small text-fg-muted">
                  Nothing saved in {monthLabel(year, month, locale)}.{' '}
                  <button type="button" onClick={() => goMonth(1)} className="font-medium text-brand-text hover:underline">
                    Try next month
                  </button>
                  .
                </p>
              )}
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <CalendarLegend />
                <Link
                  href="/saved"
                  className="inline-flex items-center gap-1.5 type-small font-medium text-brand-text hover:underline"
                >
                  <CalendarRange className="size-4" aria-hidden />
                  All saved events
                </Link>
              </div>
            </>
          )}
        </div>

        <EventPanelHost
          event={selected?.event ?? null}
          highlightDeadline={selected?.viaDeadline ?? false}
          onClose={() => setSelected(null)}
          onUnsave={handleUnsave}
        />
      </div>
    </div>
  )
}

function truncate(s: string, max = 44): string {
  return s.length <= max ? s : `${s.slice(0, max - 1).trimEnd()}…`
}
