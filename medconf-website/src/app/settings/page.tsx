// src/app/settings/page.tsx
'use client'

import { useState, useEffect } from 'react'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'
import type { NotificationPreferences } from '@/lib/types'
import { Settings, Bell, Mail, Clock, Loader2, Check, AlertCircle } from 'lucide-react'

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
        .eq('user_id', user!.id)
        .single()

      if (data) setPrefs(data)
      setLoading(false)
    }

    fetchPrefs()
  }, [user])

  const handleSave = async () => {
    if (!prefs || !user) return
    
    setSaving(true)
    
    await supabase.from('notification_preferences').update({
      new_event_alerts: prefs.new_event_alerts,
      deadline_reminders: prefs.deadline_reminders,
      notification_channel: prefs.notification_channel,
      digest_frequency: prefs.digest_frequency
    }).eq('user_id', user.id)

    setSaving(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  }

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

  const toggle = (key: 'new_event_alerts' | 'deadline_reminders') =>
    setPrefs(p => p ? { ...p, [key]: !p[key] } : p)

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-grid-pattern">
      {/* Background */}
      <div className="fixed inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 -z-10" />
      
      <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Page header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-violet-500/20 to-purple-500/20 border border-violet-500/30 flex items-center justify-center">
              <Settings className="w-5 h-5 text-violet-400" />
            </div>
            <h1 className="text-3xl font-bold text-white font-display">Notification Settings</h1>
          </div>
          <p className="text-slate-400 ml-13">Manage how and when we contact you</p>
        </div>

        <div className="glass-card rounded-2xl p-6 sm:p-8 space-y-8">
          {/* Alert toggles */}
          <div className="space-y-6">
            <h2 className="font-bold text-white text-lg flex items-center gap-2">
              <Bell className="w-5 h-5 text-cyan-400" />
              Alerts
            </h2>
            
            {[
              { 
                key: 'new_event_alerts' as const, 
                label: 'New event alerts', 
                desc: 'Be notified when new conferences matching your specialty are added' 
              },
              { 
                key: 'deadline_reminders' as const, 
                label: 'Deadline reminders', 
                desc: 'Get reminders for abstract submission and early-bird registration deadlines on saved conferences' 
              },
            ].map(item => (
              <div key={item.key} className="flex items-start justify-between gap-4 p-4 bg-slate-800/30 rounded-xl">
                <div>
                  <p className="font-medium text-white">{item.label}</p>
                  <p className="text-sm text-slate-400 mt-1">{item.desc}</p>
                </div>
                <button 
                  onClick={() => toggle(item.key)}
                  className={`relative w-12 h-7 rounded-full transition-all flex-shrink-0 ${
                    prefs[item.key] ? 'bg-cyan-500' : 'bg-slate-700'
                  }`}
                >
                  <span 
                    className={`absolute top-1 left-1 w-5 h-5 bg-white rounded-full shadow transition-transform ${
                      prefs[item.key] ? 'translate-x-5' : ''
                    }`} 
                  />
                </button>
              </div>
            ))}
          </div>

          {/* Channel */}
          <div className="space-y-4">
            <h2 className="font-bold text-white text-lg flex items-center gap-2">
              <Mail className="w-5 h-5 text-cyan-400" />
              Notification Channel
            </h2>
            <select 
              value={prefs.notification_channel} 
              onChange={e => setPrefs(p => p ? { ...p, notification_channel: e.target.value } : p)}
              className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all appearance-none cursor-pointer"
            >
              <option value="email" className="bg-slate-800">Email only</option>
              <option value="both" className="bg-slate-800">Email and in-app</option>
            </select>
          </div>

          {/* Frequency */}
          <div className="space-y-4">
            <h2 className="font-bold text-white text-lg flex items-center gap-2">
              <Clock className="w-5 h-5 text-cyan-400" />
              Digest Frequency
            </h2>
            <select 
              value={prefs.digest_frequency} 
              onChange={e => setPrefs(p => p ? { ...p, digest_frequency: e.target.value } : p)}
              className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all appearance-none cursor-pointer"
            >
              <option value="immediate" className="bg-slate-800">Immediate</option>
              <option value="daily" className="bg-slate-800">Daily digest</option>
              <option value="weekly" className="bg-slate-800">Weekly digest</option>
            </select>
          </div>

          {/* Save button */}
          <div className="pt-4">
            <button 
              onClick={handleSave}
              disabled={saving}
              className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-cyan-500 to-teal-500 text-white py-3 rounded-xl font-semibold hover:from-cyan-400 hover:to-teal-400 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-cyan-500/25"
            >
              {saving ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Check className="w-4 h-4" />
                  Save Preferences
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


