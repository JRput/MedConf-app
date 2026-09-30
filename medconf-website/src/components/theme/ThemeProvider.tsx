'use client'

import * as React from 'react'
import { ThemeProvider as NextThemesProvider } from 'next-themes'

/**
 * Light is the product default, but a first-time visitor gets whatever their
 * OS says (`defaultTheme="system"` + `enableSystem`). After that the choice is
 * persisted by next-themes in localStorage under `medconf-theme`.
 *
 * `disableTransitionOnChange` stops every transitioned property on the page
 * from animating at once when the class flips — the flip should be instant.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      storageKey="medconf-theme"
    >
      {children}
    </NextThemesProvider>
  )
}
