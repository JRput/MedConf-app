'use client'

import { useSyncExternalStore } from 'react'

/** `navigator.language` never changes within a page's life, so there is nothing to subscribe to. */
const noopSubscribe = () => () => {}

/**
 * The viewer's locale for month and weekday LABELS only — the grid itself is
 * always Monday-first (the owner's UK call), regardless of what this returns.
 *
 * Read through `useSyncExternalStore` rather than during render: the server
 * has no `navigator`, so a plain read would hydrate with different text than
 * was sent and React would throw the markup away. The server snapshot is
 * `en-GB`, which is also the right answer for most of this product's users,
 * so the correction is invisible.
 */
export function useLocale(fallback = 'en-GB'): string {
  return useSyncExternalStore(
    noopSubscribe,
    () => (typeof navigator === 'undefined' ? fallback : navigator.language || fallback),
    () => fallback
  )
}
