// src/app/auth/verify/page.tsx
// Server component: reads the query on the server so the reason copy is in the
// first HTML (no client-only flash), then hands off to the resend island.
import { safeNextPath } from '@/lib/auth/password'
import { isLikelyEmail } from '@/lib/auth/errors'
import { VerifyPanel } from './VerifyPanel'

type Params = Record<string, string | string[] | undefined>
const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? ''

export default async function VerifyPage({ searchParams }: { searchParams: Promise<Params> }) {
  const sp = await searchParams
  // Anything that is not a plain email is treated as unknown (field shown).
  const rawEmail = first(sp.email).trim()
  const email = isLikelyEmail(rawEmail) ? rawEmail : ''
  const rawReason = first(sp.reason)
  const reason = rawReason === 'unconfirmed' || rawReason === 'expired' ? rawReason : null
  const next = safeNextPath(first(sp.next), '')
  return <VerifyPanel email={email} reason={reason} next={next} />
}
