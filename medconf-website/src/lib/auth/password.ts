// src/lib/auth/password.ts
// Pure helpers for the password-reset flow: new-password validation (mirrors
// the signup rule of at least 8 characters) and an open-redirect guard for the
// `next` query parameter on /auth/callback.

export const MIN_PASSWORD_LENGTH = 8

export function validateNewPassword(password: string, confirm: string): { password?: string; confirm?: string } {
  const errors: { password?: string; confirm?: string } = {}
  if (!password) errors.password = 'Choose a password'
  else if (password.length < MIN_PASSWORD_LENGTH) errors.password = 'Password must be at least 8 characters'

  if (!confirm) errors.confirm = 'Re-enter your new password'
  else if (password !== confirm) errors.confirm = 'Passwords do not match'
  return errors
}

/**
 * Returns `next` only when it is a same-origin relative path; otherwise the
 * fallback. Rejects protocol-relative ("//host"), backslashes, schemes, and
 * any whitespace or control characters.
 */
export function safeNextPath(next: string | null | undefined, fallback: string): string {
  if (!next) return fallback
  if (!next.startsWith('/') || next.startsWith('//')) return fallback
  if (next.includes('\\')) return fallback
  if (/[\s\u0000-\u001f\u007f]/.test(next)) return fallback
  // A colon in the first path segment would read as a scheme to some parsers.
  if (/^\/[^/?#]*:/.test(next)) return fallback
  return next
}
