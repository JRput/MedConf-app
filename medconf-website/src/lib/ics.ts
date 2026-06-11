// src/lib/ics.ts
// Tiny client-side ICS (RFC 5545) generator. We emit one VEVENT for
// the conference itself, plus a second VEVENT for the abstract deadline
// when present (folks tend to want both on their calendar so an
// approaching deadline shows up alongside the conference itself).

import type { Conference } from './types'

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

export function generateIcs(c: Conference): string {
  const lines: string[] = []
  lines.push('BEGIN:VCALENDAR')
  lines.push('VERSION:2.0')
  lines.push('PRODID:-//MedConf//EN')
  lines.push('CALSCALE:GREGORIAN')
  lines.push('METHOD:PUBLISH')

  const stamp = nowIcs()

  // Conference VEVENT (all-day; DTEND is exclusive — add 1 day)
  if (c.start_date) {
    const end = c.end_date && c.end_date >= c.start_date ? c.end_date : c.start_date
    const location = [c.venue_name, c.city, c.region].filter(Boolean).join(', ') || (c.event_format === 'online' ? 'Online' : '')
    lines.push('BEGIN:VEVENT')
    lines.push(`UID:medconf-${c.id}@medconf`)
    lines.push(`DTSTAMP:${stamp}`)
    lines.push(`DTSTART;VALUE=DATE:${dateOnly(c.start_date)}`)
    lines.push(`DTEND;VALUE=DATE:${dayAfter(end)}`)
    lines.push(fold(`SUMMARY:${escapeText(c.conference_name)}`))
    if (location) lines.push(fold(`LOCATION:${escapeText(location)}`))
    if (c.description) lines.push(fold(`DESCRIPTION:${escapeText(c.description)}`))
    if (c.booking_url) lines.push(fold(`URL:${c.booking_url}`))
    lines.push('END:VEVENT')
  }

  // Abstract deadline VEVENT — a separate event so it shows up
  // independently on calendars
  if (c.abstract_deadline) {
    lines.push('BEGIN:VEVENT')
    lines.push(`UID:medconf-${c.id}-abstract@medconf`)
    lines.push(`DTSTAMP:${stamp}`)
    lines.push(`DTSTART;VALUE=DATE:${dateOnly(c.abstract_deadline)}`)
    lines.push(`DTEND;VALUE=DATE:${dayAfter(c.abstract_deadline)}`)
    lines.push(fold(`SUMMARY:${escapeText(`Abstract deadline: ${c.conference_name}`)}`))
    if (c.booking_url) lines.push(fold(`URL:${c.booking_url}`))
    lines.push('END:VEVENT')
  }

  lines.push('END:VCALENDAR')
  return lines.join('\r\n')
}

export function downloadIcs(c: Conference) {
  const ics = generateIcs(c)
  const blob = new Blob([ics], { type: 'text/calendar;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  const slug = c.conference_name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60)
  a.href = url
  a.download = `${slug || 'conference'}.ics`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
