'use client'

import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { TAB_LABEL, TAB_ORDER, type QueueTab } from '@/lib/community/moderation'
import type { TabCounts } from '@/hooks/useModeration'
import { cn } from '@/lib/utils'

/** Queue status tabs with counts. Scrolls sideways on narrow screens instead of wrapping. */
export function StatusTabs({ value, counts, onChange }: { value: QueueTab; counts: TabCounts; onChange: (t: QueueTab) => void }) {
  return (
    <Tabs value={value} onValueChange={(v) => onChange(v as QueueTab)} className="min-w-0">
      <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <TabsList variant="line" className="h-11 w-max min-w-full justify-start gap-1 border-b border-border pb-0" aria-label="Contribution status">
          {TAB_ORDER.map((t) => (
            <TabsTrigger
              key={t}
              value={t}
              className="h-11 flex-none rounded-none px-3 text-fg-muted data-[state=active]:text-fg-strong group-data-[orientation=horizontal]/tabs:after:bottom-0"
            >
              {TAB_LABEL[t]}
              <span
                className={cn(
                  'min-w-5 rounded-sm px-1 text-center font-mono text-[0.6875rem] leading-5',
                  t === 'pending' && counts[t] > 0 ? 'bg-warn-subtle text-warn-text' : 'bg-surface-muted text-fg-subtle'
                )}
              >
                {counts[t]}
              </span>
            </TabsTrigger>
          ))}
        </TabsList>
      </div>
    </Tabs>
  )
}
