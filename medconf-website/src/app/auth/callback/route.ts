// src/app/auth/callback/route.ts
// Supabase auth callback — handles email verification + OAuth redirects.
// On success, sends the user to /onboarding. The route guard there will
// bounce them straight to /dashboard if their profile is already complete.
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { createServerClient } from '@supabase/ssr'

export async function GET(request: NextRequest) {
  const requestUrl = new URL(request.url)
  const code = requestUrl.searchParams.get('code')
  const error = requestUrl.searchParams.get('error')
  const error_description = requestUrl.searchParams.get('error_description')

  if (error) {
    console.error('Email verification error:', error, error_description)
    return NextResponse.redirect(
      new URL(`/auth/login?error=${encodeURIComponent(error_description || 'Verification failed')}`, requestUrl)
    )
  }

  if (code) {
    const supabase = createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      {
        cookies: {
          getAll() {
            return request.cookies.getAll()
          },
          setAll(cookiesToSet) {
            cookiesToSet.forEach(({ name, value }) => {
              request.cookies.set(name, value)
            })
          },
        }
      }
    )

    const { error: exchangeError } = await supabase.auth.exchangeCodeForSession(code)

    if (exchangeError) {
      console.error('Failed to exchange code for session:', exchangeError)
      return NextResponse.redirect(
        new URL(`/auth/login?error=${encodeURIComponent('Failed to verify email. Please try again.')}`, requestUrl)
      )
    }

    return NextResponse.redirect(new URL('/onboarding', requestUrl))
  }

  return NextResponse.redirect(new URL('/auth/login', requestUrl))
}

