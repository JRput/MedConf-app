// src/app/saved/page.tsx
'use client'

import { useState, useEffect } from 'react'
import { createSupabaseClient } from '@/lib/supabase'
import { ConferenceCard } from '@/components/conferences/ConferenceCard'
import type { Conference, PricingTier } from '@/lib/types'
import { useAuth } from '@/hooks/useAuth'
import { Bookmark, Loader2, Calendar } from 'lucide-react'
import Link from 'next/link'

export default function SavedPage() {
  const [conferences, setConferences] = useState<Conference[]>([])
  const [pricingMap, setPricingMap] = useState<Record<number, PricingTier[]>>({})
  const [loading, setLoading] = useState(true)
  const { user } = useAuth()
  const supabase = createSupabaseClient()

  useEffect(() => {
    if (!user) return

    async function fetchSaved() {
      // Get the user's saved conference IDs
      const { data: saved } = await supabase
        .from('saved_conferences')
        .select('conference_id')
        .eq('user_id', user!.id)

      if (!saved || saved.length === 0) { 
        setLoading(false)
        return 
      }

      const ids = saved.map(s => s.conference_id)

      // Fetch the full conference records
      const { data: confs } = await supabase
        .from('conferences')
        .select('*')
        .in('id', ids)

      if (confs) setConferences(confs)

      // Fetch pricing tiers for these conferences
      const { data: tiers } = await supabase
        .from('pricing_tiers')
        .select('*')
        .in('conference_id', ids)

      if (tiers) {
        const map: Record<number, PricingTier[]> = {}
        tiers.forEach(t => { 
          if (!map[t.conference_id]) map[t.conference_id] = []
          map[t.conference_id].push(t) 
        })
        setPricingMap(map)
      }

      setLoading(false)
    }

    fetchSaved()
  }, [user])

  if (loading) {
    return (
      <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-8 h-8 text-cyan-400 animate-spin mx-auto mb-4" />
          <p className="text-slate-400 text-sm">Loading saved conferences...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-grid-pattern">
      {/* Background */}
      <div className="fixed inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 -z-10" />
      
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Page header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-rose-500/20 to-pink-500/20 border border-rose-500/30 flex items-center justify-center">
              <Bookmark className="w-5 h-5 text-rose-400" />
            </div>
            <h1 className="text-3xl font-bold text-white font-display">Saved Conferences</h1>
          </div>
          <p className="text-slate-400 ml-13">Your bookmarked conferences for quick access</p>
        </div>

        {conferences.length === 0 ? (
          <div className="glass-card rounded-xl p-12 text-center max-w-xl mx-auto">
            <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-slate-800/50 flex items-center justify-center">
              <Bookmark className="w-8 h-8 text-slate-500" />
            </div>
            <h2 className="text-lg font-semibold text-white mb-2">No saved conferences yet</h2>
            <p className="text-slate-400 mb-6">
              Browse the directory and click the save button on conferences you&apos;re interested in.
            </p>
            <Link 
              href="/conferences"
              className="inline-flex items-center gap-2 bg-gradient-to-r from-cyan-500 to-teal-500 text-white px-6 py-3 rounded-xl font-semibold hover:from-cyan-400 hover:to-teal-400 transition-all shadow-lg shadow-cyan-500/25"
            >
              <Calendar className="w-4 h-4" />
              Browse Conferences
            </Link>
          </div>
        ) : (
          <>
            <p className="text-sm text-slate-400 mb-4">
              <span className="text-white font-semibold">{conferences.length}</span> saved conference{conferences.length !== 1 ? 's' : ''}
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {conferences.map(c => (
                <ConferenceCard key={c.id} conference={c} tiers={pricingMap[c.id] || []} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}


