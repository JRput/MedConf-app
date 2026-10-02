// src/lib/supabase-server.ts
// Read-only Supabase client for server components / generateMetadata.
// Mirrors the bare client in app/api/directory/route.ts: no cookie
// plumbing, anon key only — this is for public data (conferences,
// pricing_tiers, course_sessions, scraper_sources) that RLS already
// exposes to anonymous reads. Never use this for anything requiring
// auth.uid() (saved_conferences, user_reminders) — those stay on the
// browser client via the hooks.
import { createServerClient } from '@supabase/ssr'

export function createSupabaseServerClient() {
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { cookies: { getAll: () => [], setAll: () => {} } }
  )
}
