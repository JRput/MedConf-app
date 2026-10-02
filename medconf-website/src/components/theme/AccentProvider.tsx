'use client'

import * as React from 'react'

export type Accent = 'teal' | 'ink'
export const ACCENTS: Accent[] = ['teal', 'ink']
export const ACCENT_STORAGE_KEY = 'medconf-accent'

/**
 * W1 only: lets the owner compare the two brand-accent candidates live on
 * /design. It writes `data-accent` on <html>, which swaps the `--brand-*`
 * ramp in globals.css. Once an accent is chosen this whole provider collapses
 * into a single hard-coded value in `:root` and can be deleted.
 */
const AccentContext = React.createContext<{
  accent: Accent
  setAccent: (a: Accent) => void
}>({ accent: 'teal', setAccent: () => {} })

export function AccentProvider({ children }: { children: React.ReactNode }) {
  const [accent, setAccentState] = React.useState<Accent>('teal')

  // Read back whatever the no-flash script already applied to <html>.
  React.useEffect(() => {
    const current = document.documentElement.dataset.accent
    if (current === 'ink' || current === 'teal') setAccentState(current)
  }, [])

  const setAccent = React.useCallback((a: Accent) => {
    setAccentState(a)
    document.documentElement.dataset.accent = a
    try {
      localStorage.setItem(ACCENT_STORAGE_KEY, a)
    } catch {
      /* private mode / blocked storage — the in-memory value still works */
    }
  }, [])

  const value = React.useMemo(() => ({ accent, setAccent }), [accent, setAccent])
  return <AccentContext.Provider value={value}>{children}</AccentContext.Provider>
}

export function useAccent() {
  return React.useContext(AccentContext)
}

/**
 * Runs before paint so the accent never flashes. Kept tiny and dependency-free
 * because it is inlined into <head>.
 */
export const accentNoFlashScript = `(function(){try{var a=localStorage.getItem('${ACCENT_STORAGE_KEY}');document.documentElement.dataset.accent=(a==='ink'||a==='teal')?a:'teal';}catch(e){document.documentElement.dataset.accent='teal';}})();`
