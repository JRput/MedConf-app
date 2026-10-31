// Pure account actions for the Settings page. Kept free of React so they can be
// unit-tested with a mocked Supabase client.

export const DELETE_CONFIRM_WORD = 'DELETE'

export const SPECIALTY_ALERT_ERROR = 'Could not update your alert setting. Please try again.'
export const DELETE_ACCOUNT_ERROR = 'We could not delete your account. You are still signed in. Please try again, or contact us if it keeps happening.'

export function canConfirmDelete(typed: string): boolean {
  return typed.trim() === DELETE_CONFIRM_WORD
}

type PrefsClient = {
  from: (table: string) => {
    upsert: (row: Record<string, unknown>, opts: { onConflict: string }) => PromiseLike<{ error: unknown }>
  }
}

type RpcClient = {
  rpc: (fn: string) => PromiseLike<{ error: unknown }>
}

export async function saveSpecialtyAlerts(
  supabase: PrefsClient,
  userId: string,
  enabled: boolean
): Promise<{ ok: boolean }> {
  try {
    const { error } = await supabase
      .from('notification_preferences')
      .upsert({ id: userId, email_new_conferences: enabled }, { onConflict: 'id' })
    return { ok: !error }
  } catch {
    return { ok: false }
  }
}

export async function deleteMyAccount(supabase: RpcClient): Promise<{ ok: boolean }> {
  try {
    const { error } = await supabase.rpc('delete_my_account')
    return { ok: !error }
  } catch {
    return { ok: false }
  }
}
