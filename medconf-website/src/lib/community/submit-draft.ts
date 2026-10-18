// localStorage draft for the /submit form. Every access is wrapped in
// try/catch: storage can be missing or throw (private windows, blocked site
// data, SSR). A draft is a convenience, never state of record.

const PREFIX = 'medconf:submit-draft:'

export interface SubmitDraft<V = unknown, F = unknown> {
  values: V
  fees: F
  savedAt: number
}

export const draftKey = (userId: string) => `${PREFIX}${userId}`

function store(storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>) {
  if (storage) return storage
  try {
    return typeof window !== 'undefined' ? window.localStorage : null
  } catch {
    return null
  }
}

export function saveDraft<V, F>(userId: string, data: { values: V; fees: F }, storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>, now = Date.now()): boolean {
  try {
    const s = store(storage)
    if (!s) return false
    s.setItem(draftKey(userId), JSON.stringify({ ...data, savedAt: now }))
    return true
  } catch {
    return false
  }
}

export function loadDraft<V = unknown, F = unknown>(userId: string, storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>): SubmitDraft<V, F> | null {
  try {
    const s = store(storage)
    if (!s) return null
    const raw = s.getItem(draftKey(userId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as SubmitDraft<V, F>
    if (!parsed || typeof parsed !== 'object' || !('values' in parsed) || !('fees' in parsed)) return null
    return parsed
  } catch {
    return null
  }
}

export function clearDraft(userId: string, storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>): void {
  try {
    store(storage)?.removeItem(draftKey(userId))
  } catch {
    /* ignore */
  }
}
