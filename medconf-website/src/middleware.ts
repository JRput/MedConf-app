// src/middleware.ts
// Route guard for the whole app.
// - Unauthenticated users hitting a gated route → /auth/login?next=<path>
// - Signed-in users on /auth/{login,signup} → a valid ?next=, else /dashboard
// - /auth/forgot-password and /auth/reset-password are reachable signed-out
//   (and signed-in: a recovery link creates a session before the reset page)
// - Signed-in users on a protected route with profile_completed_at = NULL
//   → /onboarding (the 3-step wizard must be finished before reaching
//     the dashboard or any other authenticated surface)
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { createServerClient } from '@supabase/ssr'
import { logGetUserError, isGatedPath, isProfileGatedPath, isUnder, loginRedirectFor, onboardingRedirectFor, resolveNext } from '@/lib/auth/gate'

// Gated surfaces (see lib/auth/gate.ts): the personal pages, the directory
// list (/conferences exactly), and /societies all need a signed-in user.
// /conferences/<id> stays a public teaser; / and /auth/* are public. Signed-out
// visitors are sent to /auth/login?next=<where they were going>.
//
// /calendar is personal by design. /submit (community event submissions)
// needs a signed-in user; /admin is additionally restricted to
// user_profiles.is_admin below.
const ADMIN_PATHS = ['/admin']
// Only the sign-in entry pages bounce a signed-in user. /auth/forgot-password
// and /auth/reset-password are intentionally NOT listed: they are reachable
// signed-out, and a signed-in user may still land on reset-password from a
// recovery link (which signs them in first).
const AUTH_PATHS = ['/auth/login', '/auth/signup']

export async function middleware(request: NextRequest) {
  let response = NextResponse.next({
    request: { headers: new Headers(request.headers) }
  })

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
            response = NextResponse.next({
              request: { headers: request.headers }
            })
            response.cookies.set(name, value, options)
          })
        },
      },
    }
  )

  const { data: { user }, error: userError } = await supabase.auth.getUser()
  logGetUserError('middleware', userError)
  const path = request.nextUrl.pathname

  // Not signed in
  if (!user) {
    if (isGatedPath(path)) {
      return NextResponse.redirect(loginRedirectFor(request.nextUrl))
    }
    return response
  }

  // Signed in
  // Bounce off the auth-entry pages
  if (isUnder(path, AUTH_PATHS)) {
    return NextResponse.redirect(new URL(resolveNext(request.nextUrl.searchParams, '/dashboard'), request.url))
  }

  // Profile completion gate. Skip the lookup on /onboarding itself
  // (the wizard needs to run there) and on the verify page.
  if (path === '/onboarding' || path.startsWith('/auth/')) {
    return response
  }

  if (isProfileGatedPath(path)) {
    // One lookup serves both gates. If the is_admin column is not there yet
    // (migration not applied), retry without it so every protected page
    // keeps working instead of bouncing everyone to /onboarding.
    let profile: { profile_completed_at: string | null; is_admin?: boolean | null } | null = null
    const full = await supabase
      .from('user_profiles')
      .select('profile_completed_at, is_admin')
      .eq('id', user.id)
      .maybeSingle()
    if (full.error) {
      const fallback = await supabase
        .from('user_profiles')
        .select('profile_completed_at')
        .eq('id', user.id)
        .maybeSingle()
      profile = fallback.data
    } else {
      profile = full.data
    }

    if (!profile?.profile_completed_at) {
      return NextResponse.redirect(onboardingRedirectFor(request.nextUrl))
    }

    if (isUnder(path, ADMIN_PATHS) && profile.is_admin !== true) {
      return NextResponse.redirect(new URL('/dashboard', request.url))
    }
  }

  return response
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|api).*)'],
}
