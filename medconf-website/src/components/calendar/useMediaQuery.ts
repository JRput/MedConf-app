'use client'

import { useCallback, useMemo, useSyncExternalStore } from 'react'

/**
 * Matches a media query.
 *
 * Used where CSS alone cannot do the job — a Sheet portals its backdrop to
 * the body, so hiding the panel with `lg:hidden` would still dim the whole
 * grid behind an inline panel on desktop. The decision has to be "don't
 * mount it", which means knowing the width in JS.
 *
 * `useSyncExternalStore` rather than useState + useEffect: `matchMedia` IS an
 * external store, and this is the hook built for one — it subscribes without
 * a setState-in-effect cascade, and its server snapshot (`initial`) is what
 * React hydrates against before swapping to the real value.
 */
export function useMediaQuery(query: string, initial = false): boolean {
  const mql = useMemo(
    () => (typeof window === 'undefined' || !window.matchMedia ? null : window.matchMedia(query)),
    [query]
  )

  const subscribe = useCallback(
    (onChange: () => void) => {
      if (!mql) return () => {}
      mql.addEventListener('change', onChange)
      return () => mql.removeEventListener('change', onChange)
    },
    [mql]
  )

  return useSyncExternalStore(
    subscribe,
    () => mql?.matches ?? initial,
    () => initial
  )
}

/** Tailwind's `lg` breakpoint — where the calendar can afford an inline side panel. */
export const LG_QUERY = '(min-width: 1024px)'
/** Tailwind's `sm` breakpoint — below this the month grid gives way to the week strip. */
export const SM_QUERY = '(min-width: 640px)'
