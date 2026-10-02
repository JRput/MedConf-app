// src/components/conferences/ReminderPanel.tsx
'use client'

import { useState, useEffect } from 'react'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'
import type { Conference, UserReminder, ReminderType, CourseSession } from '@/lib/types'
import { upcomingSessions } from '@/lib/conference-helpers'
import { Bell, Plus, X, Clock, AlertCircle, Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

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

const selectClass =
  'w-full appearance-none cursor-pointer rounded-md border border-border bg-surface px-3 py-2 type-small text-fg transition-colors duration-150 focus:border-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'

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
    <section className="space-y-4 rounded-lg border border-border bg-surface p-5">
      <div className="flex items-center justify-between">
        <h2 className="type-h3 flex items-center gap-2 text-fg-strong">
          <Bell className="size-4 text-fg-subtle" strokeWidth={1.75} aria-hidden />
          Reminders
        </h2>
        {!showForm && (
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1.5 type-small font-medium text-brand-text hover:underline"
          >
            <Plus className="size-4" aria-hidden />
            Add reminder
          </button>
        )}
      </div>

      {loading ? (
        <p className="type-small text-fg-subtle">Loading reminders…</p>
      ) : reminders.length === 0 && !showForm ? (
        <p className="type-small text-fg-muted">
          Get a notification in advance so you don&apos;t miss the deadline.
        </p>
      ) : (
        <ul className="space-y-2">
          {reminders.map(r => (
            <li
              key={r.id}
              className="flex items-center gap-3 rounded-md border border-border-subtle bg-surface-muted px-3 py-2.5"
            >
              <Clock className={cn('size-4', r.status === 'sent' ? 'text-fg-subtle' : 'text-warn-text')} aria-hidden />
              <div className="min-w-0 flex-1">
                <p className={cn('type-small', r.status === 'sent' ? 'text-fg-subtle' : 'text-fg')}>
                  {TYPE_LABEL[r.reminder_type]} · {r.lead_time_days} day{r.lead_time_days === 1 ? '' : 's'} before
                </p>
                <p className="type-caption text-fg-subtle">
                  {r.status === 'sent'
                    ? `Sent ${new Date(r.sent_at ?? r.scheduled_for).toLocaleDateString('en-GB')}`
                    : `Fires ${new Date(r.scheduled_for).toLocaleDateString('en-GB')}`}
                </p>
              </div>
              {r.status !== 'sent' && (
                <button
                  onClick={() => cancelReminder(r.id)}
                  aria-label="Cancel reminder"
                  className="text-fg-subtle transition-colors duration-150 hover:text-danger-text"
                >
                  <X className="size-4" aria-hidden />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {justSaved && (
        <div className="flex items-center gap-2 rounded-md border border-ok-border bg-ok-subtle px-3 py-2 type-small text-ok-text">
          <Check className="size-4" aria-hidden /> Reminder set.
        </div>
      )}

      {showForm && (
        <div className="space-y-3 border-t border-border-subtle pt-4">
          {isCourse ? (
            <div>
              <label className="mb-1.5 block type-caption font-medium text-fg-muted">Which session</label>
              <select
                value={selectedSessionDate || availableSessions[0]?.start_date || ''}
                onChange={e => setSelectedSessionDate(e.target.value)}
                className={selectClass}
              >
                {availableSessions.map(s => {
                  const dateLabel = new Date(s.start_date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
                  const locLabel = s.city ?? 'Online'
                  const soldOut = s.availability_status === 'sold_out' ? ' · SOLD OUT' : ''
                  return (
                    <option key={s.id} value={s.start_date}>
                      {dateLabel} · {locLabel}{soldOut}
                    </option>
                  )
                })}
              </select>
            </div>
          ) : (
            <div>
              <label className="mb-1.5 block type-caption font-medium text-fg-muted">Remind me about</label>
              <select
                value={reminderType}
                onChange={e => setReminderType(e.target.value as ReminderType)}
                className={selectClass}
              >
                {availableTypes.map(t => (
                  <option key={t.type} value={t.type}>{t.label}</option>
                ))}
              </select>
            </div>
          )}
          <div>
            <label className="mb-1.5 block type-caption font-medium text-fg-muted">When</label>
            <select
              value={leadDays}
              onChange={e => setLeadDays(Number(e.target.value))}
              className={selectClass}
            >
              {LEAD_TIMES.map(lt => (
                <option key={lt.days} value={lt.days}>{lt.label}</option>
              ))}
            </select>
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-md border border-danger-border bg-danger-subtle px-3 py-2 type-caption text-danger-text">
              <AlertCircle className="size-4 shrink-0" aria-hidden />
              {error}
            </div>
          )}

          <div className="flex gap-2">
            <Button variant="outline" onClick={() => { setShowForm(false); setError('') }}>
              Cancel
            </Button>
            <Button className="flex-1" onClick={handleAdd} disabled={saving}>
              {saving ? 'Setting…' : 'Set reminder'}
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}

const TYPE_LABEL: Record<ReminderType, string> = {
  abstract_deadline: 'Abstract deadline',
  conference_start: 'Conference start',
  registration_deadline: 'Registration deadline',
}
