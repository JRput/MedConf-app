// src/hooks/useDebouncedValue.ts
'use client'

import { useEffect, useState } from 'react'

/** Returns `value`, but delayed by `delayMs` of no further changes. */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])

  return debounced
}
