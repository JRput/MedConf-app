// src/app/auth/callback/route.ts
// This file is REQUIRED by Supabase auth for email verification callback
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { createServerClient } from '@supabase/ssr'

export async function GET(request: NextRequest) {
  const requestUrl = new URL(request.url)
  const code = requestUrl.searchParams.get('code')
  const error = requestUrl.searchParams.get('error')
  const error_description = requestUrl.searchParams.get('error_description')

  // Handle error cases (e.g., expired link, invalid code)
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
            cookiesToSet.forEach(({ name, value, options }) => {
              request.cookies.set(name, value)
            })
          },
        }
      }
    )

    const { error: exchangeError, data } = await supabase.auth.exchangeCodeForSession(code)
    
    // #region agent log
    console.log('[DEBUG-A] After exchangeCodeForSession:', {hasError:!!exchangeError,errorMsg:exchangeError?.message,hasData:!!data,userId:data?.user?.id});
    // #endregion
    
    if (exchangeError) {
      console.error('Failed to exchange code for session:', exchangeError)
      return NextResponse.redirect(
        new URL(`/auth/login?error=${encodeURIComponent('Failed to verify email. Please try again.')}`, requestUrl)
      )
    }

    // #region agent log
    console.log('[DEBUG-A] Redirecting to setup-profile');
    // #endregion

    // After successful verification, redirect to profile setup page
    // The profile setup page will handle creating the profile from localStorage
    return NextResponse.redirect(new URL('/auth/setup-profile', requestUrl))
  }

  // Fallback redirect
  return NextResponse.redirect(new URL('/auth/login', requestUrl))
}

