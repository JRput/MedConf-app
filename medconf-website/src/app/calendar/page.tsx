// src/app/calendar/page.tsx
// The personal calendar. Protected by middleware (see PROTECTED_PATHS) — a
// signed-out visitor never reaches this component, so there is no signed-out
// branch to render here.
//
// The shell is server-rendered and the events load client-side through
// useSavedConferences, the same hook /saved and /dashboard read, so the page
// needs no query of its own.
import { Suspense } from 'react'
import type { Metadata } from 'next'
import { CalendarClient } from '@/components/calendar/CalendarClient'
import { Skeleton } from '@/components/ui/skeleton'

export const metadata: Metadata = {
  title: 'Your calendar — MedConf',
  description: 'Your saved conferences, courses and abstract deadlines on one month grid.',
}

export default function CalendarPage() {
  return (
    // CalendarClient reads useSearchParams for its view/month state, which
    // needs a Suspense boundary to stay statically renderable.
    <Suspense fallback={<CalendarSkeleton />}>
      <CalendarClient />
    </Suspense>
  )
}

function CalendarSkeleton() {
  return (
    <div className="mx-auto max-w-[1320px] px-4 py-8 sm:px-6">
      <Skeleton className="h-9 w-56" />
      <Skeleton className="mt-3 h-4 w-40" />
      <Skeleton className="mt-6 h-[28rem] w-full rounded-lg" />
    </div>
  )
}
