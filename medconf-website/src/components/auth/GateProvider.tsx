'use client'

// src/components/auth/GateProvider.tsx
//
// One session lookup and one SignInGate for a whole page. Without it every
// GatedLink on the homepage (30+) would create its own Supabase client and
// auth subscription. Outside a provider the context default is "signed out,
// gate unavailable", so a GatedLink degrades to a plain link rather than
// throwing.

import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import type { User } from '@supabase/supabase-js'
import { useAuth } from '@/hooks/useAuth'
import { SignInGate } from './SignInGate'

interface GateCopy {
  title?: string
  body?: string
}

interface GateContextValue {
  user: User | null
  /** null when no provider is mounted. */
  openGate: ((next: string, copy?: GateCopy) => void) | null
}

const GateContext = createContext<GateContextValue>({ user: null, openGate: null })

export function useGate(): GateContextValue {
  return useContext(GateContext)
}

export function GateProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  const [state, setState] = useState<{ open: boolean; next?: string; copy?: GateCopy }>({ open: false })

  const openGate = useCallback((next: string, copy?: GateCopy) => setState({ open: true, next, copy }), [])
  const value = useMemo(() => ({ user, openGate }), [user, openGate])

  return (
    <GateContext.Provider value={value}>
      {children}
      <SignInGate
        open={state.open && !user}
        onOpenChange={(open) => setState((s) => ({ ...s, open }))}
        next={state.next}
        title={state.copy?.title}
        body={state.copy?.body}
      />
    </GateContext.Provider>
  )
}
