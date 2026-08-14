// src/app/settings/page.tsx
'use client'

import { useState, useEffect } from 'react'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'
import type { NotificationPreferences } from '@/lib/types'
import { Settings, Bell, Clock, Loader2, Check, AlertCircle } from 'lucide-react'

type ToggleKey = 'email_new_conferences' | 'email_abstract_deadlines' | 'email_price_changes'

export default function SettingsPage() {
  const { user } = useAuth()
  const supabase = createSupabaseClient()
  const [prefs, setPrefs] = useState<NotificationPreferences | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (!user) return

    async function fetchPrefs() {
      const { data } = await supabase
        .from('notification_preferences')
        .select('*')
        .eq('id', user!.id)
        .maybeSingle()

      if (data) {
        setPrefs(data)
      } else {
        // Lazily create defaults if the row is missing (shouldn't usually
        // happen — onboarding writes one — but make settings self-healing).
        const defaults = {
          id: user!.id,
          email_new_conferences: true,
          email_abstract_deadlines: true,
          email_price_changes: false,
          email_frequency: 'weekly',
        }
        const { data: inserted } = await supabase
          .from('notification_preferences')
          .insert(defaults)
          .select('*')
          .single()
        if (inserted) setPrefs(inserted)
      }
      setLoading(false)
    }

    fetchPrefs()
  }, [user, supabase])

  const handleSave = async () => {
    if (!prefs || !user) return

    setSaving(true)

    await supabase.from('notification_preferences').update({
      email_new_conferences: prefs.email_new_conferences,
      email_abstract_deadlines: prefs.email_abstract_deadlines,
      email_price_changes: prefs.email_price_changes,
      email_frequency: prefs.email_frequency,
    }).eq('id', user.id)

    setSaving(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  }

  const toggle = (key: ToggleKey) =>
    setPrefs(p => p ? { ...p, [key]: !p[key] } : p)

  if (loading) {
    return (
      <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-8 h-8 text-cyan-400 animate-spin mx-auto mb-4" />
          <p className="text-slate-400 text-sm">Loading preferences...</p>
        </div>
      </div>
    )
  }

  if (!prefs) {
    return (
      <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center px-4">
        <div className="text-center">
          <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-rose-500/10 border border-rose-500/20 flex items-center justify-center">
            <AlertCircle className="w-8 h-8 text-rose-400" />
          </div>
          <p className="text-slate-400">Could not load preferences. Please try again later.</p>
        </div>
      </div>
    )
  }

  const toggles: { key: ToggleKey; label: string; desc: string }[] = [
    {
      key: 'email_new_conferences',
      label: 'New conferences in your specialty',
      desc: 'Be notified when new conferences matching your specialty are added to the directory',
    },
    {
      key: 'email_abstract_deadlines',
      label: 'Abstract deadline reminders',
      desc: 'Get reminders as abstract submission deadlines approach on your saved conferences',
    },
    {
      key: 'email_price_changes',
      label: 'Price changes',
      desc: 'Get notified when registration pricing changes on your saved conferences',
    },
  ]

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-grid-pattern">
      <div className="fixed inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 -z-10" />

      <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-violet-500/20 to-purple-500/20 border border-violet-500/30 flex items-center justify-center">
              <Settings className="w-5 h-5 text-violet-400" />
            </div>
            <h1 className="text-3xl font-bold text-white font-display">Notification settings</h1>
          </div>
          <p className="text-slate-400 ml-13">Choose which alerts you want to receive</p>
        </div>

        <div className="glass-card rounded-2xl p-6 sm:p-8 space-y-8">
          <div className="space-y-6">
            <h2 className="font-bold text-white text-lg flex items-center gap-2">
              <Bell className="w-5 h-5 text-cyan-400" />
              Alerts
            </h2>

            <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-sm text-amber-200">
              <strong className="font-semibold">Email digests are not yet available.</strong>{' '}
              The preferences below are saved to your profile but no
              emails are sent yet. In-app notifications for saved-event
              reminders and specialty alerts are live and can be viewed
              from the bell icon.
            </div>

            {toggles.map(item => (
              <div key={item.key} className="flex items-start justify-between gap-4 p-4 bg-slate-800/30 rounded-xl opacity-60">
                <div>
                  <p className="font-medium text-white flex items-center gap-2">
                    {item.label}
                    <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40">
                      Coming soon
                    </span>
                  </p>
                  <p className="text-sm text-slate-400 mt-1">{item.desc}</p>
                </div>
                <button
                  disabled
                  aria-disabled="true"
                  className={`relative w-12 h-7 rounded-full flex-shrink-0 bg-slate-700 cursor-not-allowed`}
                >
                  <span className="absolute top-1 left-1 w-5 h-5 bg-white/40 rounded-full shadow" />
                </button>
              </div>
            ))}
          </div>

          <div className="space-y-4 opacity-60">
            <h2 className="font-bold text-white text-lg flex items-center gap-2">
              <Clock className="w-5 h-5 text-cyan-400" />
              Digest frequency
              <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40">
                Coming soon
              </span>
            </h2>
            <select
              disabled
              value={prefs.email_frequency}
              onChange={e => setPrefs(p => p ? { ...p, email_frequency: e.target.value } : p)}
              className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white cursor-not-allowed appearance-none"
            >
              <option value="immediate" className="bg-slate-800">Immediate</option>
              <option value="daily" className="bg-slate-800">Daily digest</option>
              <option value="weekly" className="bg-slate-800">Weekly digest</option>
            </select>
          </div>

          <div className="pt-4">
            <button
              onClick={handleSave}
              disabled={saving}
              className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-cyan-500 to-teal-500 text-white py-3 rounded-xl font-semibold hover:from-cyan-400 hover:to-teal-400 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-cyan-500/25"
            >
              {saving ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Saving…
                </>
              ) : (
                <>
                  <Check className="w-4 h-4" />
                  Save preferences
                </>
              )}
            </button>

            {saved && (
              <p className="text-emerald-400 text-sm text-center mt-4 flex items-center justify-center gap-2">
                <Check className="w-4 h-4" />
                Preferences saved successfully
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
