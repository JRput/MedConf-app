'use client'

import { CalendarDays, ChevronLeft, ChevronRight, Download, LayoutGrid, List } from 'lucide-react'
import { cn } from '@/lib/utils'
import { monthLabel } from '@/lib/calendar'
import { Button } from '@/components/ui/button'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useLocale } from './useLocale'
import type { CalendarView } from './view'

/**
 * The calendar's one row of chrome: where you are, how to move, and how to
 * get the data out.
 *
 * Month/Agenda is a segmented toggle rather than tabs — it switches the
 * rendering of one dataset, it does not navigate between two pages, and tabs
 * would imply the latter.
 */
export function CalendarHeader({
  year,
  month,
  view,
  monthCount,
  totalCount,
  showGridOnPhone,
  onToggleGridOnPhone,
  onPrev,
  onNext,
  onToday,
  onViewChange,
  onExportAll,
}: {
  year: number
  month: number
  view: CalendarView
  /** Saved events touching the month in view. */
  monthCount: number
  /** Saved events in total, for the agenda's subtitle. */
  totalCount: number
  showGridOnPhone: boolean
  onToggleGridOnPhone: () => void
  onPrev: () => void
  onNext: () => void
  onToday: () => void
  onViewChange: (view: CalendarView) => void
  onExportAll: () => void
}) {
  const locale = useLocale()
  const isMonth = view === 'month'

  return (
    <div className="mb-4 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="type-h1 text-fg-strong">
            {isMonth ? monthLabel(year, month, locale) : 'Your calendar'}
          </h1>
          <p className="mt-1 type-small text-fg-muted">
            {isMonth ? (
              <>
                {monthCount} saved event{monthCount === 1 ? '' : 's'} this month
              </>
            ) : (
              <>
                {totalCount} saved event{totalCount === 1 ? '' : 's'}, upcoming first
              </>
            )}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <ToggleGroup
            type="single"
            variant="outline"
            value={view}
            onValueChange={(v) => v && onViewChange(v as CalendarView)}
            aria-label="Calendar view"
          >
            <ToggleGroupItem value="month" aria-label="Month view">
              <LayoutGrid className="size-4" aria-hidden />
              Month
            </ToggleGroupItem>
            <ToggleGroupItem value="agenda" aria-label="Agenda view">
              <List className="size-4" aria-hidden />
              Agenda
            </ToggleGroupItem>
          </ToggleGroup>

          <Button variant="outline" size="sm" onClick={onExportAll}>
            <Download className="size-4" aria-hidden />
            <span className="hidden sm:inline">Export all (.ics)</span>
            <span className="sm:hidden">Export</span>
          </Button>
        </div>
      </div>

      {isMonth && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-1">
            <NavButton label="Previous month" onClick={onPrev}>
              <ChevronLeft className="size-4" strokeWidth={2} aria-hidden />
            </NavButton>
            <Button variant="outline" size="sm" onClick={onToday}>
              Today
            </Button>
            <NavButton label="Next month" onClick={onNext}>
              <ChevronRight className="size-4" strokeWidth={2} aria-hidden />
            </NavButton>
            <span className="ml-1 hidden type-mono-label text-fg-subtle lg:inline">
              ← → months · T today
            </span>
          </div>

          {/* Phones default to the week strip; this is the way back to the grid. */}
          <Button variant="ghost" size="sm" className="sm:hidden" onClick={onToggleGridOnPhone}>
            {showGridOnPhone ? (
              <>
                <List className="size-4" aria-hidden />
                Week view
              </>
            ) : (
              <>
                <CalendarDays className="size-4" aria-hidden />
                Month grid
              </>
            )}
          </Button>
        </div>
      )}
    </div>
  )
}

function NavButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={cn(
        // 36px visual, 44px hit area on touch — the kit's rule for icon-only controls.
        'relative inline-flex size-9 items-center justify-center rounded-md border border-border bg-surface text-fg-muted shadow-xs',
        'transition-colors duration-150 hover:border-border-strong hover:bg-surface-hover hover:text-fg',
        'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-bg focus-visible:outline-none',
        'after:absolute after:top-1/2 after:left-1/2 after:size-11 after:-translate-x-1/2 after:-translate-y-1/2 after:content-[""]'
      )}
    >
      {children}
    </button>
  )
}
