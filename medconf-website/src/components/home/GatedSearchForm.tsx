'use client'

// src/components/home/GatedSearchForm.tsx
//
// The search box is the call to action. Signed in: straight to the directory.
// Signed out: the sign-in gate opens with `next` carrying the term, so intent
// survives the detour. Still a real GET form, so without JS the browser goes
// to /conferences?q= and the route gate sends it to sign-in with `next`.
// No animation on submit — it is the frequent path.

import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PRESS } from '@/components/community/press'
import { useGate } from '@/components/auth/GateProvider'

export function GatedSearchForm() {
  const { user, openGate } = useGate()
  const router = useRouter()
  const [term, setTerm] = useState('')

  return (
    <form
      action="/conferences"
      method="get"
      role="search"
      className="mt-8 max-w-xl"
      onSubmit={(e) => {
        const q = term.trim()
        const target = q ? `/conferences?q=${encodeURIComponent(q)}` : '/conferences'
        if (user) {
          e.preventDefault()
          router.push(target)
        } else if (openGate) {
          e.preventDefault()
          openGate(target, {
            title: 'Unlock the directory with a free account',
            body: 'A free account unlocks full search, fees, CPD points and abstract deadlines. Your search is kept.',
          })
        }
      }}
    >
      <label htmlFor="home-search" className="sr-only">
        Search medical conferences, courses and CPD events
      </label>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3.5 size-[1.125rem] -translate-y-1/2 text-fg-subtle" aria-hidden />
          <Input
            id="home-search"
            name="q"
            type="search"
            autoComplete="off"
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="Search by title, specialty or location…"
            className="h-12 pl-11 text-base md:text-base focus-visible:ring-[3px] focus-visible:ring-ring"
          />
        </div>
        <Button type="submit" size="lg" className={`h-12 px-5 ${PRESS}`}>
          Search
        </Button>
      </div>
    </form>
  )
}
