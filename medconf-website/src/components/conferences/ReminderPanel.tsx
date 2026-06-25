// src/components/conferences/ReminderPanel.tsx
'use client'

import { useState, useEffect } from 'react'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'
import type { Conference, UserReminder, ReminderType, CourseSession } from '@/lib/types'
import { upcomingSessions } from '@/lib/conference-helpers'
import { Bell, Plus, X, Clock, AlertCircle, Check } from 'lucide-react'

interface Props {
  conference: Conference
  sessions?: CourseSession[]
}

const LEAD_TIMES = [
  { days: 1, label: '1 day before' },
  { days: 3, label: '3 days before' },
  { days: 7, label: '1 week before' },
  { days: 14, label: '2 weeks before' },
  { days: 30, label: '1 month before' },
]

export function ReminderPanel({ conference, sessions }: Props) {
  const { user } = useAuth()
  const supabase = createSupabaseClient()
  const [reminders, setReminders] = useState<UserReminder[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [reminderType, setReminderType] = useState<ReminderType>('abstract_deadline')
  const [leadDays, setLeadDays] = useState<number>(7)
  // For courses, the user picks a specific upcoming session to be reminded
  // about. selectedSessionDate is the session's start_date — it becomes the
  // target_date for the reminder row.
  const [selectedSessionDate, setSelectedSessionDate] = useState<string>('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [justSaved, setJustSaved] = useState(false)

  // Only multi-session courses use the session picker. Single-date courses
  // (no course_sessions rows) fall back to the conventional date-based
  // reminder so users can still set one.
  const isCourse = conference.event_type === 'course' && (sessions?.length ?? 0) > 0
  const availableSessions = isCourse ? upcomingSessions(sessions) : []

  // Available reminder types for THIS event. Courses use 'conference_start'
  // with a per-session target_date (one user_reminders row per session-
  // reminder; we still call the type 'conference_start' since the firing
  // logic and DB enum is shared).
  const availableTypes: { type: ReminderType; label: string; targetDate: string | null }[] = isCourse
    ? (availableSessions.length > 0
        ? [{ type: 'conference_start', label: 'Course session', targetDate: selectedSessionDate || availableSessions[0].start_date }]
        : [])
    : [
        conference.abstract_deadline
          ? { type: 'abstract_deadline', label: 'Abstract deadline', targetDate: conference.abstract_deadline }
          : null,
        conference.start_date
          ? { type: 'conference_start', label: 'Conference start', targetDate: conference.start_date }
          : null,
      ].filter((t): t is { type: ReminderType; label: string; targetDate: string } => t !== null)

  useEffect(() => {
    if (!user) return
    const load = async () => {
      const { data } = await supabase
        .from('user_reminders')
        .select('*')
        .eq('user_id', user.id)
        .eq('conference_id', conference.id)
        .order('scheduled_for', { ascending: true })
      if (data) setReminders(data as UserReminder[])
      setLoading(false)
    }
    load()
  }, [user, conference.id, supabase])

  // Default to whichever type is available when opening the form
  useEffect(() => {
    if (showForm && availableTypes.length > 0) {
      const firstAvail = availableTypes[0].type
      if (!availableTypes.find(t => t.type === reminderType)) {
        setReminderType(firstAvail)
      }
    }
  }, [showForm])

  if (!user) return null
  if (availableTypes.length === 0) return null

  const handleAdd = async () => {
    setError('')

    // For courses, the target_date is the chosen session's start_date.
    // For conferences, it comes from availableTypes (deadline / start).
    let targetDate: string | null = null
    let effectiveType: ReminderType = reminderType
    if (isCourse) {
      effectiveType = 'conference_start'
      targetDate = selectedSessionDate || availableSessions[0]?.start_date || null
      if (!targetDate) {
        setError('No upcoming sessions available.')
        return
      }
    } else {
      const typeInfo = availableTypes.find(t => t.type === reminderType)
      if (!typeInfo || !typeInfo.targetDate) {
        setError('This conference does not have a date for that reminder.')
        return
      }
      targetDate = typeInfo.targetDate
    }

    const target = new Date(targetDate)
    const scheduled = new Date(target.getTime() - leadDays * 86400_000)
    const today = new Date(new Date().toISOString().slice(0, 10))

    if (scheduled < today) {
      setError(`That date has already passed (would have fired on ${scheduled.toLocaleDateString('en-GB')}).`)
      return
    }

    setSaving(true)
    const { error: insertError, data } = await supabase
      .from('user_reminders')
      .insert({
        user_id: user.id,
        conference_id: conference.id,
        reminder_type: effectiveType,
        lead_time_days: leadDays,
        target_date: targetDate,
        scheduled_for: scheduled.toISOString().slice(0, 10),
        status: 'scheduled',
      })
      .select('*')
      .single()

    setSaving(false)
    if (insertError) {
      if (insertError.code === '23505') {
        setError('You already have a reminder for that combination.')
      } else {
        setError(insertError.message || 'Could not create the reminder.')
      }
      return
    }

    if (data) setReminders(prev => [...prev, data as UserReminder].sort((a, b) => a.scheduled_for.localeCompare(b.scheduled_for)))
    setShowForm(false)
    setJustSaved(true)
    setTimeout(() => setJustSaved(false), 2500)
  }

  const cancelReminder = async (id: string) => {
    const { error } = await supabase
      .from('user_reminders')
      .delete()
      .eq('id', id)
      .eq('user_id', user.id)
    if (!error) {
      setReminders(prev => prev.filter(r => r.id !== id))
    }
  }

  return (
    <div className="glass-card rounded-xl p-5 sm:p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-bold text-white text-lg flex items-center gap-2">
          <Bell className="w-5 h-5 text-cyan-400" />
          Reminders
        </h2>
        {!showForm && (
          <button
            onClick={() => setShowForm(true)}
            className="text-sm flex items-center gap-1.5 text-cyan-400 hover:text-cyan-300"
          >
            <Plus className="w-4 h-4" />
            Add reminder
          </button>
        )}
      </div>

      {loading ? (
        <p className="text-sm text-slate-500">Loading reminders…</p>
      ) : reminders.length === 0 && !showForm ? (
        <p className="text-sm text-slate-400">
          Get a notification in advance so you don&apos;t miss the deadline.
        </p>
      ) : (
        <ul className="space-y-2">
          {reminders.map(r => (
            <li
              key={r.id}
              className="flex items-center gap-3 px-3 py-2.5 bg-slate-800/40 border border-slate-800 rounded-lg"
            >
              <Clock className={`w-4 h-4 ${r.status === 'sent' ? 'text-slate-500' : 'text-amber-400'}`} />
              <div className="flex-1 min-w-0">
                <p className={`text-sm ${r.status === 'sent' ? 'text-slate-400' : 'text-white'}`}>
                  {TYPE_LABEL[r.reminder_type]} · {r.lead_time_days} day{r.lead_time_days === 1 ? '' : 's'} before
                </p>
                <p className="text-xs text-slate-500">
                  {r.status === 'sent'
                    ? `Sent ${new Date(r.sent_at ?? r.scheduled_for).toLocaleDateString('en-GB')}`
                    : `Fires ${new Date(r.scheduled_for).toLocaleDateString('en-GB')}`}
                </p>
              </div>
              {r.status !== 'sent' && (
                <button
                  onClick={() => cancelReminder(r.id)}
                  aria-label="Cancel reminder"
                  className="text-slate-500 hover:text-rose-400"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {justSaved && (
        <div className="flex items-center gap-2 text-sm text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2">
          <Check className="w-4 h-4" /> Reminder set.
        </div>
      )}

      {showForm && (
        <div className="space-y-3 border-t border-slate-800 pt-4">
          {isCourse ? (
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">Which session</label>
              <select
                value={selectedSessionDate || availableSessions[0]?.start_date || ''}
                onChange={e => setSelectedSessionDate(e.target.value)}
                className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all appearance-none cursor-pointer"
              >
                {availableSessions.map(s => {
                  const dateLabel = new Date(s.start_date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
                  const locLabel = s.city ?? 'Online'
                  const soldOut = s.availability_status === 'sold_out' ? ' · SOLD OUT' : ''
                  return (
                    <option key={s.id} value={s.start_date} className="bg-slate-800">
                      {dateLabel} · {locLabel}{soldOut}
                    </option>
                  )
                })}
              </select>
            </div>
          ) : (
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">Remind me about</label>
              <select
                value={reminderType}
                onChange={e => setReminderType(e.target.value as ReminderType)}
                className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all appearance-none cursor-pointer"
              >
                {availableTypes.map(t => (
                  <option key={t.type} value={t.type} className="bg-slate-800">{t.label}</option>
                ))}
              </select>
            </div>
          )}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">When</label>
            <select
              value={leadDays}
              onChange={e => setLeadDays(Number(e.target.value))}
              className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all appearance-none cursor-pointer"
            >
              {LEAD_TIMES.map(lt => (
                <option key={lt.days} value={lt.days} className="bg-slate-800">{lt.label}</option>
              ))}
            </select>
          </div>

          {error && (
            <div className="flex items-center gap-2 text-rose-400 text-xs bg-rose-500/10 border border-rose-500/20 rounded-lg px-3 py-2">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              {error}
            </div>
          )}

          <div className="flex gap-2">
            <button
              onClick={() => { setShowForm(false); setError('') }}
              className="px-3 py-2 text-sm border border-slate-700 rounded-lg text-slate-300 hover:bg-slate-800/50 transition-all"
            >
              Cancel
            </button>
            <button
              onClick={handleAdd}
              disabled={saving}
              className="flex-1 px-3 py-2 text-sm bg-gradient-to-r from-cyan-500 to-teal-500 text-white rounded-lg font-medium hover:from-cyan-400 hover:to-teal-400 disabled:opacity-50 transition-all"
            >
              {saving ? 'Setting…' : 'Set reminder'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

const TYPE_LABEL: Record<ReminderType, string> = {
  abstract_deadline: 'Abstract deadline',
  conference_start: 'Conference start',
  registration_deadline: 'Registration deadline',
}
