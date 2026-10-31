import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { SpecialtyAlertToggle } from '@/components/settings/SpecialtyAlertToggle'
import { DeleteAccountSection } from '@/components/settings/DeleteAccountSection'
import {
  canConfirmDelete,
  deleteMyAccount,
  saveSpecialtyAlerts,
} from '@/components/settings/actions'

describe('canConfirmDelete', () => {
  it('requires the exact word DELETE', () => {
    expect(canConfirmDelete('')).toBe(false)
    expect(canConfirmDelete('delete')).toBe(false)
    expect(canConfirmDelete('DELET')).toBe(false)
    expect(canConfirmDelete('DELETE')).toBe(true)
  })
})

describe('deleteMyAccount', () => {
  it('calls rpc delete_my_account exactly once with no arguments', async () => {
    const rpc = vi.fn().mockResolvedValue({ error: null })
    const r = await deleteMyAccount({ rpc })
    expect(rpc).toHaveBeenCalledTimes(1)
    expect(rpc).toHaveBeenCalledWith('delete_my_account')
    expect(r.ok).toBe(true)
  })
  it('reports failure on error or throw without leaking text', async () => {
    expect((await deleteMyAccount({ rpc: vi.fn().mockResolvedValue({ error: { message: 'boom' } }) })).ok).toBe(false)
    expect((await deleteMyAccount({ rpc: vi.fn().mockRejectedValue(new Error('net')) })).ok).toBe(false)
  })
})

describe('saveSpecialtyAlerts', () => {
  it('upserts the boolean on conflict id', async () => {
    const upsert = vi.fn().mockResolvedValue({ error: null })
    const from = vi.fn().mockReturnValue({ upsert })
    const r = await saveSpecialtyAlerts({ from }, 'u1', false)
    expect(from).toHaveBeenCalledWith('notification_preferences')
    expect(upsert).toHaveBeenCalledWith({ id: 'u1', email_new_conferences: false }, { onConflict: 'id' })
    expect(r.ok).toBe(true)
  })
  it('reports failure so the UI can roll back', async () => {
    const upsert = vi.fn().mockResolvedValue({ error: { code: '42501' } })
    const r = await saveSpecialtyAlerts({ from: () => ({ upsert }) }, 'u1', true)
    expect(r.ok).toBe(false)
  })
})

describe('markup', () => {
  it('toggle reflects state and label', () => {
    const on = renderToStaticMarkup(<SpecialtyAlertToggle checked onChange={() => {}} />)
    expect(on).toContain('In-app alerts for new events in my specialty')
    expect(on).toContain('aria-checked="true"')
    const off = renderToStaticMarkup(<SpecialtyAlertToggle checked={false} onChange={() => {}} error="Nope" />)
    expect(off).toContain('aria-checked="false"')
    expect(off).toContain('Nope')
  })
  it('delete section explains what is deleted and starts collapsed', () => {
    const html = renderToStaticMarkup(<DeleteAccountSection onConfirm={() => {}} />)
    expect(html).toContain('saved events')
    expect(html).toContain('published')
    expect(html).toContain('without your name')
    expect(html).not.toContain('delete-confirm')
  })
})
