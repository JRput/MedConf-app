// src/lib/__tests__/format.test.ts
import { describe, expect, it } from 'vitest'
import { isOngoing } from '../format'

function inDays(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() + n)
  return d.toISOString().slice(0, 10)
}

describe('isOngoing', () => {
  it('is true once an event has started but not yet ended', () => {
    expect(isOngoing(inDays(-10), inDays(10))).toBe(true)
  })

  it('is false for an event that has not started yet', () => {
    expect(isOngoing(inDays(1), inDays(10))).toBe(false)
  })

  it('is false for an event that has already ended', () => {
    expect(isOngoing(inDays(-20), inDays(-1))).toBe(false)
  })

  it('is false for a single-day or missing-end-date event', () => {
    expect(isOngoing(inDays(-1), null)).toBe(false)
    expect(isOngoing(null, inDays(1))).toBe(false)
  })

  it('treats "ends today" as still ongoing', () => {
    expect(isOngoing(inDays(-5), inDays(0))).toBe(true)
  })
})
