// src/app/auth/callback/route.ts
// Supabase auth callback for email links: sign-up verification, password
// recovery and email-change confirmation.
//
// Two entry shapes are supported:
//   ?code=...                      PKCE flow (default Supabase template). The
//                                  code verifier lives in the browser that
//                                  requested the email, so the link must be
//                                  opened on that device.
//   ?token_hash=...&type=...       Server-side template flow
//                                  ({{ .SiteURL }}/auth/callback?token_hash=
//                                  {{ .TokenHash }}&type=recovery). Works from
//                                  any device.
//
// `next` (relative paths only, see safeNextPath) says where to land. Default is
// /auth/reset-password for recovery, otherwise /onboarding (its guard bounces
// completed profiles to /dashboard).
//
// Session cookies are buffered in setAll and written onto the redirect
// response. Writing them only to request.cookies (the old behaviour) never
// reached the browser, so verified users were not actually signed in.
// Failures redirect with short codes only, never free text (see
// lib/auth/errors.ts): recovery -> /auth/forgot-password?error=expired,
// everything else -> /auth/login?error=verify_failed. Details are logged
// server-side. Accepted OTP types are the four the app uses: signup, email,
// recovery, email_change (no magiclink or invite).
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { createServerClient } from '@supabase/ssr'
import type { EmailOtpType } from '@supabase/supabase-js'
import { safeNextPath } from '@/lib/auth/password'

const OTP_TYPES: readonly EmailOtpType[] = ['signup', 'email', 'recovery', 'email_change']

type CookieToSet = { name: string; value: string; options?: Parameters<NextResponse['cookies']['set']>[2] }

export async function GET(request: NextRequest) {
  const requestUrl = new URL(request.url)
  const params = requestUrl.searchParams
  const code = params.get('code')
  const tokenHash = params.get('token_hash')
  const rawType = params.get('type')
  const type = OTP_TYPES.find((t) => t === rawType)
  const error = params.get('error')
  const errorDescription = params.get('error_description')

  const isRecovery = rawType === 'recovery'
  const next = safeNextPath(params.get('next'), isRecovery ? '/auth/reset-password' : '/onboarding')

  const failure = () =>
    NextResponse.redirect(
      new URL(isRecovery ? '/auth/forgot-password?error=expired' : '/auth/login?error=verify_failed', requestUrl)
    )

  if (error) {
    console.error('Auth callback error:', error, errorDescription)
    return failure()
  }

  if (!code && !(tokenHash && type)) {
    return NextResponse.redirect(new URL('/auth/login', requestUrl))
  }

  const pending: CookieToSet[] = []
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll()
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach((c) => pending.push(c))
        },
      },
    }
  )

  const { error: authError } = code
    ? await supabase.auth.exchangeCodeForSession(code)
    : await supabase.auth.verifyOtp({ type: type!, token_hash: tokenHash! })

  if (authError) {
    console.error('Auth callback failed:', authError)
    // A PKCE recovery link opened on a different device arrives as ?code= with
    // no `type`; the reset destination tells us it was a recovery attempt.
    if (!isRecovery && next === '/auth/reset-password') {
      return NextResponse.redirect(new URL('/auth/forgot-password?error=expired', requestUrl))
    }
    return failure()
  }

  const response = NextResponse.redirect(new URL(next, requestUrl))
  pending.forEach(({ name, value, options }) => response.cookies.set(name, value, options))
  return response
}
