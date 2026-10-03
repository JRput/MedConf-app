// src/lib/ics.ts
// Tiny client-side ICS (RFC 5545) generator. We emit one VEVENT for
// the conference itself, plus a second VEVENT for the abstract deadline
// when present (folks tend to want both on their calendar so an
// approaching deadline shows up alongside the conference itself).
//
// Two entry points, one body of rules:
//   generateIcs(conference)   — the detail page's "Export .ics" button
//   generateIcsFeed(events[]) — /calendar's "Export all", every saved event
//                               in a single VCALENDAR
// Both go through `icsEvents()`, so a one-event download and a 40-event feed
// agree on UIDs, all-day handling and escaping.

import type { Conference } from './types'
import type { DirectoryEvent } from './directory'

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

function dateOnly(iso: string): string {
  // YYYY-MM-DD → YYYYMMDD
  return iso.slice(0, 10).replace(/-/g, '')
}

function nowIcs(): string {
  const d = new Date()
  return `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}T${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}Z`
}

function dayAfter(iso: string): string {
  // Adds a day for ICS all-day events (DTEND is exclusive)
  const d = new Date(iso + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() + 1)
  return `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}`
}

function escapeText(s: string): string {
  return s.replace(/\\/g, '\\\\').replace(/\n/g, '\\n').replace(/,/g, '\\,').replace(/;/g, '\\;')
}

function fold(line: string): string {
  // ICS lines should not exceed 75 octets. Fold longer ones with CRLF + space.
  if (line.length <= 75) return line
  const chunks: string[] = []
  let i = 0
  while (i < line.length) {
    const size = i === 0 ? 75 : 74
    chunks.push(line.slice(i, i + size))
    i += size
  }
  return chunks.join('\r\n ')
}

/**
 * The common shape both entry points reduce to. `Conference` rows and the
 * `DirectoryEvent` view-model carry the same facts under different names, so
 * normalising once here is what keeps a single download and the whole-calendar
 * feed from drifting apart.
 */
interface IcsEvent {
  id: number
  name: string
  startDate: string | null
  endDate: string | null
  abstractDeadline: string | null
  location: string
  description?: string | null
  url?: string | null
}

function fromConference(c: Conference): IcsEvent {
  return {
    id: c.id,
    name: c.conference_name,
    startDate: c.start_date,
    endDate: c.end_date,
    abstractDeadline: c.abstract_deadline,
    location: [c.venue_name, c.city, c.region].filter(Boolean).join(', ') || (c.event_format === 'online' ? 'Online' : ''),
    description: c.description,
    url: c.booking_url,
  }
}

function fromDirectoryEvent(e: DirectoryEvent): IcsEvent {
  return {
    id: e.id,
    name: e.name,
    startDate: e.startDate,
    endDate: e.endDate,
    abstractDeadline: e.abstractDeadline,
    location: [e.city, e.region].filter(Boolean).join(', ') || (e.format === 'online' ? 'Online' : ''),
    // The view-model has no description/booking link; the event's own page is
    // the useful thing to carry into an external calendar anyway.
    url: typeof window === 'undefined' ? null : new URL(e.href, window.location.origin).toString(),
  }
}

/** The VEVENT block(s) for one event: the event itself, plus its abstract deadline. */
function icsEvents(e: IcsEvent, stamp: string): string[] {
  const lines: string[] = []

  // All-day event; DTEND is exclusive, hence the +1 day.
  if (e.startDate) {
    const end = e.endDate && e.endDate >= e.startDate ? e.endDate : e.startDate
    lines.push('BEGIN:VEVENT')
    lines.push(`UID:medconf-${e.id}@medconf`)
    lines.push(`DTSTAMP:${stamp}`)
    lines.push(`DTSTART;VALUE=DATE:${dateOnly(e.startDate)}`)
    lines.push(`DTEND;VALUE=DATE:${dayAfter(end)}`)
    lines.push(fold(`SUMMARY:${escapeText(e.name)}`))
    if (e.location) lines.push(fold(`LOCATION:${escapeText(e.location)}`))
    if (e.description) lines.push(fold(`DESCRIPTION:${escapeText(e.description)}`))
    if (e.url) lines.push(fold(`URL:${e.url}`))
    lines.push('END:VEVENT')
  }

  // A separate VEVENT so an approaching deadline shows up on its own date
  // rather than being buried in the conference's description.
  if (e.abstractDeadline) {
    lines.push('BEGIN:VEVENT')
    lines.push(`UID:medconf-${e.id}-abstract@medconf`)
    lines.push(`DTSTAMP:${stamp}`)
    lines.push(`DTSTART;VALUE=DATE:${dateOnly(e.abstractDeadline)}`)
    lines.push(`DTEND;VALUE=DATE:${dayAfter(e.abstractDeadline)}`)
    lines.push(fold(`SUMMARY:${escapeText(`Abstract deadline: ${e.name}`)}`))
    if (e.url) lines.push(fold(`URL:${e.url}`))
    lines.push('END:VEVENT')
  }

  return lines
}

function wrapCalendar(body: string[], name?: string): string {
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//MedConf//EN', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH']
  if (name) {
    // Non-standard but near-universally honoured, and it is the difference
    // between "MedConf saved events" and "Untitled calendar" in the import
    // dialog of every client people actually use.
    lines.push(fold(`X-WR-CALNAME:${escapeText(name)}`))
  }
  lines.push(...body)
  lines.push('END:VCALENDAR')
  return lines.join('\r\n')
}

export function generateIcs(c: Conference): string {
  return wrapCalendar(icsEvents(fromConference(c), nowIcs()))
}

/**
 * One VCALENDAR holding every event passed in — /calendar's "Export all".
 * Undated saves are skipped silently: there is nothing to put on a calendar
 * date, and inventing one would misfile the event in the user's real diary.
 */
export function generateIcsFeed(events: readonly DirectoryEvent[], name = 'MedConf — saved events'): string {
  const stamp = nowIcs()
  const body = events
    .filter((e) => e.startDate || e.abstractDeadline)
    .flatMap((e) => icsEvents(fromDirectoryEvent(e), stamp))
  return wrapCalendar(body, name)
}

/** How many of these events will actually appear in the feed. */
export function icsFeedCount(events: readonly DirectoryEvent[]): number {
  return events.filter((e) => e.startDate || e.abstractDeadline).length
}

function triggerDownload(ics: string, filename: string) {
  const blob = new Blob([ics], { type: 'text/calendar;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function slugify(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60)
}

export function downloadIcs(c: Conference) {
  triggerDownload(generateIcs(c), `${slugify(c.conference_name) || 'conference'}.ics`)
}

/** Download every saved event as a single importable file. */
export function downloadIcsFeed(events: readonly DirectoryEvent[], filename = 'medconf-saved-events.ics') {
  triggerDownload(generateIcsFeed(events), filename)
}
