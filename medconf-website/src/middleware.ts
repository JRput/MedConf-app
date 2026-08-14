// src/middleware.ts
// Route guard for the whole app.
// - Unauthenticated users hitting a protected route → /auth/login
// - Signed-in users on /auth/{login,signup} → /dashboard
// - Signed-in users on a protected route with profile_completed_at = NULL
//   → /onboarding (the 3-step wizard must be finished before reaching
//     the dashboard or any other authenticated surface)
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { createServerClient } from '@supabase/ssr'

// /conferences is intentionally PUBLIC — the directory is the product's
// discovery surface and gating it defeats both the public-read RLS
// policy on conferences/pricing_tiers and SEO. Personal surfaces
// (/saved, /settings, /dashboard) and the signup wizard (/onboarding)
// stay protected.
const PROTECTED_PATHS = ['/saved', '/settings', '/dashboard', '/onboarding']
const AUTH_PATHS = ['/auth/login', '/auth/signup']

function isUnder(path: string, candidates: string[]) {
  return candidates.some(p => path === p || path.startsWith(p + '/'))
}

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

  const { data: { user } } = await supabase.auth.getUser()
  const path = request.nextUrl.pathname

  // Not signed in
  if (!user) {
    if (isUnder(path, PROTECTED_PATHS)) {
      return NextResponse.redirect(new URL('/auth/login', request.url))
    }
    return response
  }

  // Signed in
  // Bounce off the auth-entry pages
  if (isUnder(path, AUTH_PATHS)) {
    return NextResponse.redirect(new URL('/dashboard', request.url))
  }

  // Profile completion gate. Skip the lookup on /onboarding itself
  // (the wizard needs to run there) and on the verify page.
  if (path === '/onboarding' || path.startsWith('/auth/')) {
    return response
  }

  if (isUnder(path, PROTECTED_PATHS)) {
    const { data: profile } = await supabase
      .from('user_profiles')
      .select('profile_completed_at')
      .eq('id', user.id)
      .maybeSingle()

    if (!profile?.profile_completed_at) {
      return NextResponse.redirect(new URL('/onboarding', request.url))
    }
  }

  return response
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|api).*)'],
}
