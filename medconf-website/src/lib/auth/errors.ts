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
