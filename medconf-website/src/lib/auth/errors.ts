// src/lib/auth/errors.ts
// Fixed copy for the short error codes /auth/callback puts in `?error=`.
// The callback never forwards free text into a URL, so a crafted link cannot
// display attacker-chosen wording on our pages. Unknown codes map to null.

const MESSAGES: Record<string, string> = {
  verify_failed:
    "We couldn't verify that link. It may have expired. Sign in, or create a new account to get a fresh one.",
  expired: 'That reset link has expired or was already used. Request a new one below.',
}

export function authErrorMessage(code: string | null | undefined): string | null {
  if (!code) return null
  return Object.prototype.hasOwnProperty.call(MESSAGES, code) ? MESSAGES[code] : null
}

export const CONFIRM_FIRST = 'Confirm your email before signing in.'

/**
 * Fixed copy for a sign-in / sign-up failure. Raw Supabase text is never
 * returned: anything unrecognised becomes a generic message.
 */
export function mapAuthError(message: string, context: 'signin' | 'signup' = 'signin'): string {
  const m = (message ?? '').toLowerCase()
  if (m.includes('rate limit') || m.includes('too many')) return 'Too many attempts. Wait a few minutes and try again.'
  if (context === 'signup' && (m.includes('password') && /weak|short|least|characters|contain|requirement|pwned|easy to guess/.test(m)))
    return 'Password does not meet the requirements.'
  if (m.includes('invalid login credentials')) return 'Email or password is incorrect.'
  if (m.includes('email not confirmed')) return CONFIRM_FIRST
  return context === 'signup' ? 'Sign-up failed. Try again.' : 'Sign-in failed. Try again.'
}

/** True when the Supabase message means the account exists but is unconfirmed. */
export function isUnconfirmedError(message: string): boolean {
  return (message ?? '').toLowerCase().includes('email not confirmed')
}

/**
 * Strict shape check for an email taken from a URL before it is echoed in the
 * page. Lives here (pure, shared by the server verify page and client code).
 */
export function isLikelyEmail(value: string | null | undefined): value is string {
  return !!value && value.length <= 254 && /^[^\s@]{1,64}@[^\s@]{1,255}\.[A-Za-z]{2,}$/.test(value) && !/[<>"'`]/.test(value)
}
