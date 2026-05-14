**MedConf**

Frontend Website

**Technical Build & Implementation Guide**

  ----------------------------------- -----------------------------------
  Version                             1.0

  Date                                February 2026

  Purpose                             Cursor frontend development
                                      reference

  Framework                           Next.js 14 + React

  Database                            Supabase (PostgreSQL)

  Hosting                             Vercel
  ----------------------------------- -----------------------------------

**1. Overview & Purpose**

This document is the complete frontend build guide for MedConf. It is
written to be used directly as a reference by Cursor to build the
website from scratch. Every page, component, hook, and configuration is
specified with production-ready code. The guide assumes the agentic
scraper is already built and populating the Supabase database with
conference data --- this frontend reads from that data and presents it
to users.

The frontend follows an Eventbrite-style MVP model: users browse a
directory of conferences, filter and search to find relevant events,
view full details, save conferences they are interested in, and are
redirected to the official organiser website to complete their booking.
MedConf does not handle payments or ticketing.

+-----------------------------------------------------------------------+
| **How to use this document**                                          |
|                                                                       |
| Each section builds on the previous one. Follow them in order. Code   |
| blocks are production-ready and specify the exact file path at the    |
| top. Environment variables are called out explicitly where needed.    |
| The Supabase setup section must be completed before any frontend code |
| will work.                                                            |
+-----------------------------------------------------------------------+

**2. Tech Stack & Dependencies**

**2.1 Technology Choices**

  ----------------- -------------------------- --------------------------
  **Component**     **Technology**             **Role**

  Framework         Next.js 14 (App Router)    Page routing, SSR, API
                                               routes, deployment
                                               optimisation

  UI Library        React 18                   Component-based UI, state
                                               management

  Styling           Tailwind CSS               Utility-first CSS --- fast
                                               styling with no custom CSS
                                               files needed

  Database Client   Supabase JS SDK            Reads conference data,
                    (@supabase/supabase-js)    handles user auth,
                                               real-time updates

  Auth              Supabase Auth (built-in)   User registration, email
                                               verification, login,
                                               session management

  Icons             Lucide React               Clean icon set for the UI

  Hosting           Vercel                     Deploys Next.js apps
                                               natively --- zero config
  ----------------- -------------------------- --------------------------

**2.2 Project Initialisation**

Run the following commands to create the project and install all
dependencies:

+-----------------------------------------------------------------------+
| \# Create the Next.js project                                         |
|                                                                       |
| npx create-next-app@latest medconf-website                            |
|                                                                       |
| \# When prompted, select these options:                               |
|                                                                       |
| \# Would you like to use TypeScript? -\> Yes                          |
|                                                                       |
| \# Would you like to use ESLint? -\> Yes                              |
|                                                                       |
| \# Would you like to use Tailwind CSS? -\> Yes                        |
|                                                                       |
| \# Would you like to use src/ directory? -\> Yes                      |
|                                                                       |
| \# Would you like to use App Router? -\> Yes                          |
|                                                                       |
| \# Would you like to customize the default import aliases? -\> No     |
|                                                                       |
| cd medconf-website                                                    |
|                                                                       |
| \# Install additional dependencies                                    |
|                                                                       |
| npm install \@supabase/supabase-js \@supabase/nextjs lucide-react     |
+-----------------------------------------------------------------------+

**3. Project Structure**

The project follows Next.js App Router conventions. Every file below
must be created. Pages live inside src/app/ and map directly to URL
routes. Components, hooks, and utilities are organised into dedicated
folders.

+-----------------------------------------------------------------------+
| medconf-website/                                                      |
|                                                                       |
| ├── .env.local \# Environment variables                               |
|                                                                       |
| ├── src/                                                              |
|                                                                       |
| │ ├── app/                                                            |
|                                                                       |
| │ │ ├── layout.tsx \# Root layout --- wraps every page                |
|                                                                       |
| │ │ ├── page.tsx \# Homepage / landing page                           |
|                                                                       |
| │ │ ├── auth/                                                         |
|                                                                       |
| │ │ │ ├── signup/page.tsx \# Registration page                        |
|                                                                       |
| │ │ │ ├── login/page.tsx \# Login page                                |
|                                                                       |
| │ │ │ ├── verify/page.tsx \# Email verification confirmation          |
|                                                                       |
| │ │ │ └── callback/route.ts \# Supabase auth callback (required)      |
|                                                                       |
| │ │ ├── conferences/                                                  |
|                                                                       |
| │ │ │ ├── page.tsx \# Conference directory listing                    |
|                                                                       |
| │ │ │ └── \[id\]/page.tsx \# Individual conference detail page        |
|                                                                       |
| │ │ ├── saved/page.tsx \# User\'s saved/bookmarked conferences        |
|                                                                       |
| │ │ └── settings/page.tsx \# Notification preferences                 |
|                                                                       |
| │ ├── components/                                                     |
|                                                                       |
| │ │ ├── layout/                                                       |
|                                                                       |
| │ │ │ ├── Navbar.tsx \# Top navigation bar                            |
|                                                                       |
| │ │ │ └── Footer.tsx \# Site footer                                   |
|                                                                       |
| │ │ ├── auth/                                                         |
|                                                                       |
| │ │ │ ├── SignUpForm.tsx \# Registration form component               |
|                                                                       |
| │ │ │ └── LoginForm.tsx \# Login form component                       |
|                                                                       |
| │ │ ├── conferences/                                                  |
|                                                                       |
| │ │ │ ├── ConferenceCard.tsx \# Card shown in the directory listing   |
|                                                                       |
| │ │ │ ├── ConferenceList.tsx \# Renders the grid of cards             |
|                                                                       |
| │ │ │ ├── FilterPanel.tsx \# Specialty, location, price filters       |
|                                                                       |
| │ │ │ ├── SearchBar.tsx \# Keyword search input                       |
|                                                                       |
| │ │ │ ├── ConferenceDetail.tsx \# Full detail view for a single       |
| conference                                                            |
|                                                                       |
| │ │ │ ├── PricingTable.tsx \# Renders pricing tiers for a conference  |
|                                                                       |
| │ │ │ └── CPDBadge.tsx \# Small badge showing CPD status + points     |
|                                                                       |
| │ │ └── ui/                                                           |
|                                                                       |
| │ │ └── SaveButton.tsx \# Bookmark / unsave toggle button             |
|                                                                       |
| │ ├── hooks/                                                          |
|                                                                       |
| │ │ ├── useAuth.ts \# Auth state --- current user, login, logout      |
|                                                                       |
| │ │ ├── useConferences.ts \# Fetches and filters conference data      |
|                                                                       |
| │ │ └── useSaved.ts \# Manages user\'s saved conferences              |
|                                                                       |
| │ ├── lib/                                                            |
|                                                                       |
| │ │ ├── supabase.ts \# Supabase client initialisation                 |
|                                                                       |
| │ │ └── types.ts \# TypeScript type definitions                       |
|                                                                       |
| │ └── middleware.ts \# Protects authenticated routes                  |
+-----------------------------------------------------------------------+

**4. Environment Variables & Supabase Client**

**4.1 .env.local**

Create this file in the project root. Replace the placeholder values
with your actual Supabase project credentials from your Supabase
dashboard.

+-----------------------------------------------------------------------+
| \# .env.local                                                         |
|                                                                       |
| NEXT_PUBLIC_SUPABASE_URL=https://your-project-id.supabase.co          |
|                                                                       |
| NEXT_PUBLIC_SUPABASE_ANON_KEY=your-supabase-anon-key-here             |
+-----------------------------------------------------------------------+

**4.2 src/lib/supabase.ts**

This file creates the Supabase client. It is imported by hooks and
components whenever they need to read data or interact with auth. The
\@supabase/nextjs package handles cookie-based sessions correctly for
Next.js server and client components.

+-----------------------------------------------------------------------+
| // src/lib/supabase.ts                                                |
|                                                                       |
| import { createBrowserClient } from \'@supabase/nextjs\'              |
|                                                                       |
| export function createSupabaseClient() {                              |
|                                                                       |
| return createBrowserClient(                                           |
|                                                                       |
| process.env.NEXT_PUBLIC_SUPABASE_URL!,                                |
|                                                                       |
| process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!                            |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**4.3 src/lib/types.ts**

All TypeScript types used across the app are defined here. Cursor should
reference this file whenever it needs to type a conference, pricing
tier, or user object.

+-----------------------------------------------------------------------+
| // src/lib/types.ts                                                   |
|                                                                       |
| export interface Conference {                                         |
|                                                                       |
| id: number                                                            |
|                                                                       |
| source_url: string                                                    |
|                                                                       |
| conference_name: string                                               |
|                                                                       |
| specialty: string \| null                                             |
|                                                                       |
| start_date: string \| null // YYYY-MM-DD                              |
|                                                                       |
| end_date: string \| null                                              |
|                                                                       |
| venue_name: string \| null                                            |
|                                                                       |
| city: string \| null                                                  |
|                                                                       |
| region: string \| null                                                |
|                                                                       |
| cpd_accredited: boolean                                               |
|                                                                       |
| cpd_points: number \| null                                            |
|                                                                       |
| abstract_open: boolean                                                |
|                                                                       |
| abstract_deadline: string \| null                                     |
|                                                                       |
| organiser_url: string \| null                                         |
|                                                                       |
| description: string \| null                                           |
|                                                                       |
| archived: boolean                                                     |
|                                                                       |
| created_at: string                                                    |
|                                                                       |
| updated_at: string                                                    |
|                                                                       |
| }                                                                     |
|                                                                       |
| export interface PricingTier {                                        |
|                                                                       |
| id: number                                                            |
|                                                                       |
| conference_id: number                                                 |
|                                                                       |
| tier_label: string                                                    |
|                                                                       |
| price_gbp: number                                                     |
|                                                                       |
| is_early_bird: boolean                                                |
|                                                                       |
| early_bird_deadline: string \| null                                   |
|                                                                       |
| }                                                                     |
|                                                                       |
| export interface UserProfile {                                        |
|                                                                       |
| id: string                                                            |
|                                                                       |
| email: string                                                         |
|                                                                       |
| role: string // e.g. Student, Consultant, Registrar, Nurse            |
|                                                                       |
| specialty: string \| null                                             |
|                                                                       |
| preferred_region: string \| null                                      |
|                                                                       |
| }                                                                     |
|                                                                       |
| export interface SavedConference {                                    |
|                                                                       |
| id: number                                                            |
|                                                                       |
| user_id: string                                                       |
|                                                                       |
| conference_id: number                                                 |
|                                                                       |
| saved_at: string                                                      |
|                                                                       |
| }                                                                     |
|                                                                       |
| export interface NotificationPreferences {                            |
|                                                                       |
| id: number                                                            |
|                                                                       |
| user_id: string                                                       |
|                                                                       |
| new_event_alerts: boolean                                             |
|                                                                       |
| deadline_reminders: boolean                                           |
|                                                                       |
| notification_channel: string // \'email\' \| \'both\'                 |
|                                                                       |
| digest_frequency: string // \'immediate\' \| \'daily\' \| \'weekly\'  |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**5. Supabase Setup --- Auth & Database**

Before any frontend code will work, Supabase must be configured
correctly. This section covers the additional tables and Row Level
Security (RLS) policies that the frontend needs. The conferences,
pricing_tiers, and scraper_sources tables are already created by the
scraper setup --- do not recreate them here.

**5.1 Additional Tables**

Run these SQL statements in your Supabase SQL Editor to create the
tables the frontend reads from and writes to:

+-----------------------------------------------------------------------+
| \-- User profiles --- stores role, specialty, and region after signup |
|                                                                       |
| CREATE TABLE IF NOT EXISTS user_profiles (                            |
|                                                                       |
| id TEXT PRIMARY KEY REFERENCES auth.users(id),                        |
|                                                                       |
| role TEXT NOT NULL, \-- Student \| Consultant \| Registrar \| Nurse   |
|                                                                       |
| specialty TEXT,                                                       |
|                                                                       |
| preferred_region TEXT,                                                |
|                                                                       |
| created_at TIMESTAMPTZ DEFAULT NOW()                                  |
|                                                                       |
| );                                                                    |
|                                                                       |
| \-- Saved / bookmarked conferences per user                           |
|                                                                       |
| CREATE TABLE IF NOT EXISTS saved_conferences (                        |
|                                                                       |
| id SERIAL PRIMARY KEY,                                                |
|                                                                       |
| user_id TEXT NOT NULL REFERENCES auth.users(id),                      |
|                                                                       |
| conference_id INTEGER NOT NULL REFERENCES conferences(id),            |
|                                                                       |
| saved_at TIMESTAMPTZ DEFAULT NOW(),                                   |
|                                                                       |
| UNIQUE(user_id, conference_id) \-- prevents duplicate saves           |
|                                                                       |
| );                                                                    |
|                                                                       |
| \-- Notification preferences per user                                 |
|                                                                       |
| CREATE TABLE IF NOT EXISTS notification_preferences (                 |
|                                                                       |
| id SERIAL PRIMARY KEY,                                                |
|                                                                       |
| user_id TEXT NOT NULL REFERENCES auth.users(id) UNIQUE,               |
|                                                                       |
| new_event_alerts BOOLEAN DEFAULT TRUE,                                |
|                                                                       |
| deadline_reminders BOOLEAN DEFAULT TRUE,                              |
|                                                                       |
| notification_channel TEXT DEFAULT \'email\', \-- \'email\' \|         |
| \'both\'                                                              |
|                                                                       |
| digest_frequency TEXT DEFAULT \'weekly\', \-- \'immediate\' \|        |
| \'daily\' \| \'weekly\'                                               |
|                                                                       |
| created_at TIMESTAMPTZ DEFAULT NOW()                                  |
|                                                                       |
| );                                                                    |
+-----------------------------------------------------------------------+

**5.2 Row Level Security (RLS) Policies**

RLS ensures users can only read their own saved conferences and
preferences, while conference data is publicly readable. Run all of
these in the SQL Editor:

+-----------------------------------------------------------------------+
| \-- Conferences: public read, no write from frontend                  |
|                                                                       |
| ALTER TABLE conferences ENABLE ROW LEVEL SECURITY;                    |
|                                                                       |
| CREATE POLICY \"Public can read conferences\"                         |
|                                                                       |
| ON conferences FOR SELECT USING (archived = FALSE);                   |
|                                                                       |
| \-- Pricing tiers: public read                                        |
|                                                                       |
| ALTER TABLE pricing_tiers ENABLE ROW LEVEL SECURITY;                  |
|                                                                       |
| CREATE POLICY \"Public can read pricing tiers\"                       |
|                                                                       |
| ON pricing_tiers FOR SELECT USING (TRUE);                             |
|                                                                       |
| \-- User profiles: users can only read/write their own                |
|                                                                       |
| ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;                  |
|                                                                       |
| CREATE POLICY \"Users can read own profile\"                          |
|                                                                       |
| ON user_profiles FOR SELECT USING (auth.uid() = id);                  |
|                                                                       |
| CREATE POLICY \"Users can insert own profile\"                        |
|                                                                       |
| ON user_profiles FOR INSERT WITH CHECK (auth.uid() = id);             |
|                                                                       |
| CREATE POLICY \"Users can update own profile\"                        |
|                                                                       |
| ON user_profiles FOR UPDATE USING (auth.uid() = id);                  |
|                                                                       |
| \-- Saved conferences: users can only manage their own                |
|                                                                       |
| ALTER TABLE saved_conferences ENABLE ROW LEVEL SECURITY;              |
|                                                                       |
| CREATE POLICY \"Users can read own saved conferences\"                |
|                                                                       |
| ON saved_conferences FOR SELECT USING (auth.uid() = user_id);         |
|                                                                       |
| CREATE POLICY \"Users can save conferences\"                          |
|                                                                       |
| ON saved_conferences FOR INSERT WITH CHECK (auth.uid() = user_id);    |
|                                                                       |
| CREATE POLICY \"Users can unsave conferences\"                        |
|                                                                       |
| ON saved_conferences FOR DELETE USING (auth.uid() = user_id);         |
|                                                                       |
| \-- Notification preferences: users can only manage their own         |
|                                                                       |
| ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY;       |
|                                                                       |
| CREATE POLICY \"Users can read own preferences\"                      |
|                                                                       |
| ON notification_preferences FOR SELECT USING (auth.uid() = user_id);  |
|                                                                       |
| CREATE POLICY \"Users can insert own preferences\"                    |
|                                                                       |
| ON notification_preferences FOR INSERT WITH CHECK (auth.uid() =       |
| user_id);                                                             |
|                                                                       |
| CREATE POLICY \"Users can update own preferences\"                    |
|                                                                       |
| ON notification_preferences FOR UPDATE USING (auth.uid() = user_id);  |
+-----------------------------------------------------------------------+

**5.3 Auth Configuration**

In your Supabase dashboard, go to Authentication \> Settings and
configure the following:

-   **Site URL.** Set this to your deployed domain (e.g.
    https://medconf.vercel.app). During development, set it to
    http://localhost:3000.

-   **Redirect URLs.** Add http://localhost:3000/auth/callback and
    https://medconf.vercel.app/auth/callback to the allowed redirect
    URLs list.

-   **Email provider.** Supabase includes a built-in email service for
    development. For production, connect a custom SMTP provider (e.g.
    SendGrid or AWS SES) via Authentication \> Settings \> SMTP.

-   **Confirm email.** Ensure \'Confirm email\' is enabled under Email
    settings. This enforces email verification before users can access
    the app.

**6. Middleware --- Route Protection**

The middleware file intercepts requests and checks whether the user is
authenticated before allowing access to protected pages. If they are not
logged in and try to access /conferences, /saved, or /settings, they are
redirected to the login page.

+-----------------------------------------------------------------------+
| // src/middleware.ts                                                  |
|                                                                       |
| import { NextResponse } from \'next/server\'                          |
|                                                                       |
| import type { NextRequest } from \'next/server\'                      |
|                                                                       |
| import { createServerClient } from \'@supabase/nextjs\'               |
|                                                                       |
| export async function middleware(request: NextRequest) {              |
|                                                                       |
| let response = NextResponse.next({                                    |
|                                                                       |
| request: { headers: new Headers(request.headers) }                    |
|                                                                       |
| })                                                                    |
|                                                                       |
| const supabase = createServerClient(                                  |
|                                                                       |
| process.env.NEXT_PUBLIC_SUPABASE_URL!,                                |
|                                                                       |
| process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,                           |
|                                                                       |
| {                                                                     |
|                                                                       |
| cookies: {                                                            |
|                                                                       |
| getAll() { return request.cookies.getAll() },                         |
|                                                                       |
| setAll(cookiesToSet) {                                                |
|                                                                       |
| cookiesToSet.forEach(({ name, value, options }) =\> {                 |
|                                                                       |
| request.cookies.set(name, value, options)                             |
|                                                                       |
| response.cookies.set(name, value, options)                            |
|                                                                       |
| })                                                                    |
|                                                                       |
| },                                                                    |
|                                                                       |
| },                                                                    |
|                                                                       |
| }                                                                     |
|                                                                       |
| )                                                                     |
|                                                                       |
| const { data: { user } } = await supabase.auth.getUser()              |
|                                                                       |
| // Protected routes --- redirect to login if not authenticated        |
|                                                                       |
| const protectedPaths = \[\'/conferences\', \'/saved\',                |
| \'/settings\'\]                                                       |
|                                                                       |
| const isProtected = protectedPaths.some(path =\>                      |
| request.nextUrl.pathname.startsWith(path))                            |
|                                                                       |
| if (isProtected && !user) {                                           |
|                                                                       |
| return NextResponse.redirect(new URL(\'/auth/login\', request.url))   |
|                                                                       |
| }                                                                     |
|                                                                       |
| // If user is logged in and hits login/signup, redirect to            |
| conferences                                                           |
|                                                                       |
| if (user && (request.nextUrl.pathname.startsWith(\'/auth/login\')     |
| \|\| request.nextUrl.pathname.startsWith(\'/auth/signup\'))) {        |
|                                                                       |
| return NextResponse.redirect(new URL(\'/conferences\', request.url))  |
|                                                                       |
| }                                                                     |
|                                                                       |
| return response                                                       |
|                                                                       |
| }                                                                     |
|                                                                       |
| export const config = {                                               |
|                                                                       |
| matcher:                                                              |
| \[\'/((?!\_next/static\|\_next/image\|favicon.ico\|api).\*)\'\],      |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**7. Hooks --- Shared Logic**

Hooks encapsulate all data fetching and state logic so components stay
clean and focused on rendering. Each hook is a self-contained unit that
Cursor can build independently.

**7.1 useAuth --- Authentication State**

+-----------------------------------------------------------------------+
| // src/hooks/useAuth.ts                                               |
|                                                                       |
| \'use client\'                                                        |
|                                                                       |
| import { useState, useEffect } from \'react\'                         |
|                                                                       |
| import { createSupabaseClient } from \'@/lib/supabase\'               |
|                                                                       |
| import type { User } from \'@supabase/supabase-js\'                   |
|                                                                       |
| export function useAuth() {                                           |
|                                                                       |
| const \[user, setUser\] = useState\<User \| null\>(null)              |
|                                                                       |
| const \[loading, setLoading\] = useState(true)                        |
|                                                                       |
| const supabase = createSupabaseClient()                               |
|                                                                       |
| useEffect(() =\> {                                                    |
|                                                                       |
| // Listen for auth state changes (login, logout, session restore)     |
|                                                                       |
| const { data: { subscription } } =                                    |
| supabase.auth.onAuthStateChange((\_, session) =\> {                   |
|                                                                       |
| setUser(session?.user ?? null)                                        |
|                                                                       |
| setLoading(false)                                                     |
|                                                                       |
| })                                                                    |
|                                                                       |
| return () =\> subscription.unsubscribe()                              |
|                                                                       |
| }, \[\])                                                              |
|                                                                       |
| const signUp = async (email: string, password: string) =\> {          |
|                                                                       |
| const { data, error } = await supabase.auth.signUp({ email, password  |
| })                                                                    |
|                                                                       |
| return { data, error }                                                |
|                                                                       |
| }                                                                     |
|                                                                       |
| const signIn = async (email: string, password: string) =\> {          |
|                                                                       |
| const { data, error } = await supabase.auth.signInWithPassword({      |
| email, password })                                                    |
|                                                                       |
| return { data, error }                                                |
|                                                                       |
| }                                                                     |
|                                                                       |
| const signOut = async () =\> {                                        |
|                                                                       |
| await supabase.auth.signOut()                                         |
|                                                                       |
| }                                                                     |
|                                                                       |
| return { user, loading, signUp, signIn, signOut }                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**7.2 useConferences --- Directory Data & Filtering**

+-----------------------------------------------------------------------+
| // src/hooks/useConferences.ts                                        |
|                                                                       |
| \'use client\'                                                        |
|                                                                       |
| import { useState, useEffect, useMemo } from \'react\'                |
|                                                                       |
| import { createSupabaseClient } from \'@/lib/supabase\'               |
|                                                                       |
| import type { Conference, PricingTier } from \'@/lib/types\'          |
|                                                                       |
| export interface Filters {                                            |
|                                                                       |
| specialty: string // \'\' means all                                   |
|                                                                       |
| region: string // \'\' means all                                      |
|                                                                       |
| maxPrice: number // 0 means no limit                                  |
|                                                                       |
| searchTerm: string                                                    |
|                                                                       |
| }                                                                     |
|                                                                       |
| export function useConferences() {                                    |
|                                                                       |
| const \[conferences, setConferences\] =                               |
| useState\<Conference\[\]\>(\[\])                                      |
|                                                                       |
| const \[pricingMap, setPricingMap\] = useState\<Record\<number,       |
| PricingTier\[\]\>\>({})                                               |
|                                                                       |
| const \[loading, setLoading\] = useState(true)                        |
|                                                                       |
| const \[filters, setFilters\] = useState\<Filters\>({                 |
|                                                                       |
| specialty: \'\', region: \'\', maxPrice: 0, searchTerm: \'\'          |
|                                                                       |
| })                                                                    |
|                                                                       |
| const supabase = createSupabaseClient()                               |
|                                                                       |
| useEffect(() =\> {                                                    |
|                                                                       |
| async function fetchData() {                                          |
|                                                                       |
| // Fetch all active (non-archived) conferences                        |
|                                                                       |
| const { data: confData } = await supabase                             |
|                                                                       |
| .from(\'conferences\')                                                |
|                                                                       |
| .select(\'\*\')                                                       |
|                                                                       |
| .eq(\'archived\', false)                                              |
|                                                                       |
| .order(\'start_date\', { ascending: true })                           |
|                                                                       |
| // Fetch all pricing tiers                                            |
|                                                                       |
| const { data: tierData } = await supabase                             |
|                                                                       |
| .from(\'pricing_tiers\')                                              |
|                                                                       |
| .select(\'\*\')                                                       |
|                                                                       |
| if (confData) setConferences(confData)                                |
|                                                                       |
| // Build a map: conference_id -\> \[tiers\]                           |
|                                                                       |
| if (tierData) {                                                       |
|                                                                       |
| const map: Record\<number, PricingTier\[\]\> = {}                     |
|                                                                       |
| tierData.forEach(t =\> {                                              |
|                                                                       |
| if (!map\[t.conference_id\]) map\[t.conference_id\] = \[\]            |
|                                                                       |
| map\[t.conference_id\].push(t)                                        |
|                                                                       |
| })                                                                    |
|                                                                       |
| setPricingMap(map)                                                    |
|                                                                       |
| }                                                                     |
|                                                                       |
| setLoading(false)                                                     |
|                                                                       |
| }                                                                     |
|                                                                       |
| fetchData()                                                           |
|                                                                       |
| }, \[\])                                                              |
|                                                                       |
| // Filtering logic --- runs client-side on the fetched data           |
|                                                                       |
| const filtered = useMemo(() =\> {                                     |
|                                                                       |
| return conferences.filter(c =\> {                                     |
|                                                                       |
| // Specialty filter                                                   |
|                                                                       |
| if (filters.specialty && c.specialty?.toLowerCase() !==               |
| filters.specialty.toLowerCase()) return false                         |
|                                                                       |
| // Region filter                                                      |
|                                                                       |
| if (filters.region && c.region?.toLowerCase() !==                     |
| filters.region.toLowerCase()) return false                            |
|                                                                       |
| // Price filter --- checks if ANY tier is under the max               |
|                                                                       |
| if (filters.maxPrice \> 0) {                                          |
|                                                                       |
| const tiers = pricingMap\[c.id\] \|\| \[\]                            |
|                                                                       |
| const hasAffordableTier = tiers.some(t =\> t.price_gbp \<=            |
| filters.maxPrice)                                                     |
|                                                                       |
| if (tiers.length \> 0 && !hasAffordableTier) return false             |
|                                                                       |
| }                                                                     |
|                                                                       |
| // Search filter --- matches name, specialty, city, or description    |
|                                                                       |
| if (filters.searchTerm) {                                             |
|                                                                       |
| const term = filters.searchTerm.toLowerCase()                         |
|                                                                       |
| const searchable = \`\${c.conference_name} \${c.specialty} \${c.city} |
| \${c.description}\`.toLowerCase()                                     |
|                                                                       |
| if (!searchable.includes(term)) return false                          |
|                                                                       |
| }                                                                     |
|                                                                       |
| return true                                                           |
|                                                                       |
| })                                                                    |
|                                                                       |
| }, \[conferences, pricingMap, filters\])                              |
|                                                                       |
| return { conferences: filtered, pricingMap, loading, filters,         |
| setFilters }                                                          |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**7.3 useSaved --- Bookmarked Conferences**

+-----------------------------------------------------------------------+
| // src/hooks/useSaved.ts                                              |
|                                                                       |
| \'use client\'                                                        |
|                                                                       |
| import { useState, useEffect } from \'react\'                         |
|                                                                       |
| import { createSupabaseClient } from \'@/lib/supabase\'               |
|                                                                       |
| import { useAuth } from \'@/hooks/useAuth\'                           |
|                                                                       |
| export function useSaved() {                                          |
|                                                                       |
| const \[savedIds, setSavedIds\] = useState\<Set\<number\>\>(new       |
| Set())                                                                |
|                                                                       |
| const { user } = useAuth()                                            |
|                                                                       |
| const supabase = createSupabaseClient()                               |
|                                                                       |
| useEffect(() =\> {                                                    |
|                                                                       |
| if (!user) return                                                     |
|                                                                       |
| async function fetchSaved() {                                         |
|                                                                       |
| const { data } = await supabase                                       |
|                                                                       |
| .from(\'saved_conferences\')                                          |
|                                                                       |
| .select(\'conference_id\')                                            |
|                                                                       |
| .eq(\'user_id\', user.id)                                             |
|                                                                       |
| if (data) setSavedIds(new Set(data.map(r =\> r.conference_id)))       |
|                                                                       |
| }                                                                     |
|                                                                       |
| fetchSaved()                                                          |
|                                                                       |
| }, \[user\])                                                          |
|                                                                       |
| const isSaved = (conferenceId: number) =\> savedIds.has(conferenceId) |
|                                                                       |
| const toggleSave = async (conferenceId: number) =\> {                 |
|                                                                       |
| if (!user) return                                                     |
|                                                                       |
| if (isSaved(conferenceId)) {                                          |
|                                                                       |
| // Remove from saved                                                  |
|                                                                       |
| await supabase.from(\'saved_conferences\').delete()                   |
|                                                                       |
| .eq(\'user_id\', user.id).eq(\'conference_id\', conferenceId)         |
|                                                                       |
| setSavedIds(prev =\> { const next = new Set(prev);                    |
| next.delete(conferenceId); return next })                             |
|                                                                       |
| } else {                                                              |
|                                                                       |
| // Add to saved                                                       |
|                                                                       |
| await supabase.from(\'saved_conferences\').insert({                   |
|                                                                       |
| user_id: user.id, conference_id: conferenceId                         |
|                                                                       |
| })                                                                    |
|                                                                       |
| setSavedIds(prev =\> new Set(\[\...prev, conferenceId\]))             |
|                                                                       |
| }                                                                     |
|                                                                       |
| }                                                                     |
|                                                                       |
| return { savedIds, isSaved, toggleSave }                              |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**8. Layout & Navigation**

**8.1 Root Layout --- src/app/layout.tsx**

+-----------------------------------------------------------------------+
| // src/app/layout.tsx                                                 |
|                                                                       |
| import type { Metadata } from \'next\'                                |
|                                                                       |
| import { Inter } from \'next/font/google\'                            |
|                                                                       |
| import \'./globals.css\'                                              |
|                                                                       |
| import { Navbar } from \'@/components/layout/Navbar\'                 |
|                                                                       |
| import { Footer } from \'@/components/layout/Footer\'                 |
|                                                                       |
| const inter = Inter({ subsets: \[\'latin\'\] })                       |
|                                                                       |
| export const metadata: Metadata = {                                   |
|                                                                       |
| title: \'MedConf --- Medical Conference Directory\',                  |
|                                                                       |
| description: \'Find and book medical conferences and CPD              |
| opportunities across the UK.\',                                       |
|                                                                       |
| }                                                                     |
|                                                                       |
| export default function RootLayout({ children }: { children:          |
| React.ReactNode }) {                                                  |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<html lang=\"en\"\>                                                  |
|                                                                       |
| \<body className={\`\${inter.className} min-h-screen flex flex-col    |
| bg-gray-50\`}\>                                                       |
|                                                                       |
| \<Navbar /\>                                                          |
|                                                                       |
| \<main className=\"flex-1 max-w-7xl mx-auto w-full px-4               |
| py-8\"\>{children}\</main\>                                           |
|                                                                       |
| \<Footer /\>                                                          |
|                                                                       |
| \</body\>                                                             |
|                                                                       |
| \</html\>                                                             |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**8.2 Navbar --- src/components/layout/Navbar.tsx**

+-----------------------------------------------------------------------+
| // src/components/layout/Navbar.tsx                                   |
|                                                                       |
| \'use client\'                                                        |
|                                                                       |
| import { useAuth } from \'@/hooks/useAuth\'                           |
|                                                                       |
| import Link from \'next/link\'                                        |
|                                                                       |
| export function Navbar() {                                            |
|                                                                       |
| const { user, signOut } = useAuth()                                   |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<nav className=\"bg-white shadow-sm border-b border-gray-200\"\>     |
|                                                                       |
| \<div className=\"max-w-7xl mx-auto px-4 flex items-center            |
| justify-between h-16\"\>                                              |
|                                                                       |
| {/\* Logo \*/}                                                        |
|                                                                       |
| \<Link href=\"/\" className=\"text-xl font-bold                       |
| text-\[#1B2845\]\"\>MedConf\</Link\>                                  |
|                                                                       |
| {/\* Navigation links \*/}                                            |
|                                                                       |
| \<div className=\"flex items-center gap-6\"\>                         |
|                                                                       |
| {user ? (                                                             |
|                                                                       |
| \<\>                                                                  |
|                                                                       |
| \<Link href=\"/conferences\" className=\"text-sm text-gray-600        |
| hover:text-\[#0E7490\] transition-colors\"\>Conferences\</Link\>      |
|                                                                       |
| \<Link href=\"/saved\" className=\"text-sm text-gray-600              |
| hover:text-\[#0E7490\] transition-colors\"\>Saved\</Link\>            |
|                                                                       |
| \<Link href=\"/settings\" className=\"text-sm text-gray-600           |
| hover:text-\[#0E7490\] transition-colors\"\>Settings\</Link\>         |
|                                                                       |
| \<button onClick={signOut} className=\"text-sm text-gray-500          |
| hover:text-red-500 transition-colors\"\>Sign Out\</button\>           |
|                                                                       |
| \</\>                                                                 |
|                                                                       |
| ) : (                                                                 |
|                                                                       |
| \<\>                                                                  |
|                                                                       |
| \<Link href=\"/auth/login\" className=\"text-sm text-gray-600         |
| hover:text-\[#0E7490\] transition-colors\"\>Sign In\</Link\>          |
|                                                                       |
| \<Link href=\"/auth/signup\" className=\"text-sm bg-\[#0E7490\]       |
| text-white px-4 py-1.5 rounded-lg hover:bg-\[#0A5A6E\]                |
| transition-colors\"\>Sign Up\</Link\>                                 |
|                                                                       |
| \</\>                                                                 |
|                                                                       |
| )}                                                                    |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \</nav\>                                                              |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**8.3 Footer --- src/components/layout/Footer.tsx**

+-----------------------------------------------------------------------+
| // src/components/layout/Footer.tsx                                   |
|                                                                       |
| export function Footer() {                                            |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<footer className=\"bg-\[#1B2845\] text-white mt-16\"\>              |
|                                                                       |
| \<div className=\"max-w-7xl mx-auto px-4 py-8 flex flex-col           |
| md:flex-row justify-between items-center gap-4\"\>                    |
|                                                                       |
| \<span className=\"text-lg font-bold\"\>MedConf\</span\>              |
|                                                                       |
| \<p className=\"text-sm text-gray-400\"\>© 2026 MedConf. All rights   |
| reserved.\</p\>                                                       |
|                                                                       |
| \<div className=\"flex gap-4 text-sm text-gray-400\"\>                |
|                                                                       |
| \<a href=\"#\" className=\"hover:text-white                           |
| transition-colors\"\>Privacy\</a\>                                    |
|                                                                       |
| \<a href=\"#\" className=\"hover:text-white                           |
| transition-colors\"\>Terms\</a\>                                      |
|                                                                       |
| \<a href=\"#\" className=\"hover:text-white                           |
| transition-colors\"\>Contact\</a\>                                    |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \</footer\>                                                           |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**9. Authentication Pages**

**9.1 Sign Up --- src/app/auth/signup/page.tsx**

+-----------------------------------------------------------------------+
| // src/app/auth/signup/page.tsx                                       |
|                                                                       |
| \'use client\'                                                        |
|                                                                       |
| import { useState } from \'react\'                                    |
|                                                                       |
| import { useAuth } from \'@/hooks/useAuth\'                           |
|                                                                       |
| import { useRouter } from \'next/navigation\'                         |
|                                                                       |
| import Link from \'next/link\'                                        |
|                                                                       |
| import { createSupabaseClient } from \'@/lib/supabase\'               |
|                                                                       |
| const ROLES = \[\'Student\', \'Registrar\', \'Consultant\',           |
| \'Nurse\', \'Other\'\]                                                |
|                                                                       |
| const SPECIALTIES = \[\'Cardiology\', \'General Practice\',           |
| \'Orthopaedics\', \'Surgery\', \'Emergency Medicine\',                |
|                                                                       |
| \'Neurology\', \'Oncology\', \'Paediatrics\', \'Psychiatry\',         |
| \'Radiology\', \'Nursing\', \'Other\'\]                               |
|                                                                       |
| const REGIONS = \[\'London\', \'South East\', \'South West\', \'East  |
| of England\', \'Midlands\',                                           |
|                                                                       |
| \'North East\', \'North West\', \'Yorkshire\', \'Wales\',             |
| \'Scotland\', \'Northern Ireland\'\]                                  |
|                                                                       |
| export default function SignUpPage() {                                |
|                                                                       |
| const { signUp } = useAuth()                                          |
|                                                                       |
| const router = useRouter()                                            |
|                                                                       |
| const supabase = createSupabaseClient()                               |
|                                                                       |
| const \[step, setStep\] = useState(1) // Step 1: email/password. Step |
| 2: profile.                                                           |
|                                                                       |
| const \[email, setEmail\] = useState(\'\')                            |
|                                                                       |
| const \[password, setPassword\] = useState(\'\')                      |
|                                                                       |
| const \[role, setRole\] = useState(\'\')                              |
|                                                                       |
| const \[specialty, setSpecialty\] = useState(\'\')                    |
|                                                                       |
| const \[region, setRegion\] = useState(\'\')                          |
|                                                                       |
| const \[error, setError\] = useState(\'\')                            |
|                                                                       |
| const \[loading, setLoading\] = useState(false)                       |
|                                                                       |
| const handleStep1 = async () =\> {                                    |
|                                                                       |
| setLoading(true); setError(\'\')                                      |
|                                                                       |
| const { data, error } = await signUp(email, password)                 |
|                                                                       |
| if (error) { setError(error.message); setLoading(false); return }     |
|                                                                       |
| setLoading(false)                                                     |
|                                                                       |
| setStep(2)                                                            |
|                                                                       |
| }                                                                     |
|                                                                       |
| const handleStep2 = async () =\> {                                    |
|                                                                       |
| setLoading(true); setError(\'\')                                      |
|                                                                       |
| // Get the current user session                                       |
|                                                                       |
| const { data: { user } } = await supabase.auth.getUser()              |
|                                                                       |
| if (!user) { setError(\'Session error. Please try again.\');          |
| setLoading(false); return }                                           |
|                                                                       |
| // Insert user profile                                                |
|                                                                       |
| const { error } = await supabase.from(\'user_profiles\').insert({     |
|                                                                       |
| id: user.id, role, specialty, preferred_region: region                |
|                                                                       |
| })                                                                    |
|                                                                       |
| if (error) { setError(error.message); setLoading(false); return }     |
|                                                                       |
| // Insert default notification preferences                            |
|                                                                       |
| await supabase.from(\'notification_preferences\').insert({ user_id:   |
| user.id })                                                            |
|                                                                       |
| setLoading(false)                                                     |
|                                                                       |
| router.push(\'/auth/verify\')                                         |
|                                                                       |
| }                                                                     |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<div className=\"max-w-md mx-auto mt-16\"\>                          |
|                                                                       |
| \<h1 className=\"text-2xl font-bold text-\[#1B2845\] text-center      |
| mb-2\"\>Create your account\</h1\>                                    |
|                                                                       |
| \<p className=\"text-gray-500 text-center text-sm mb-6\"\>Step {step} |
| of 2\</p\>                                                            |
|                                                                       |
| {step === 1 ? (                                                       |
|                                                                       |
| \<div className=\"bg-white rounded-xl shadow-sm border                |
| border-gray-200 p-6 space-y-4\"\>                                     |
|                                                                       |
| \<div\>                                                               |
|                                                                       |
| \<label className=\"block text-sm font-medium text-gray-700           |
| mb-1\"\>Email\</label\>                                               |
|                                                                       |
| \<input type=\"email\" value={email} onChange={e =\>                  |
| setEmail(e.target.value)}                                             |
|                                                                       |
| className=\"w-full px-3 py-2 border border-gray-300 rounded-lg        |
| text-sm focus:outline-none focus:ring-2 focus:ring-\[#0E7490\]\" /\>  |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \<div\>                                                               |
|                                                                       |
| \<label className=\"block text-sm font-medium text-gray-700           |
| mb-1\"\>Password\</label\>                                            |
|                                                                       |
| \<input type=\"password\" value={password} onChange={e =\>            |
| setPassword(e.target.value)}                                          |
|                                                                       |
| className=\"w-full px-3 py-2 border border-gray-300 rounded-lg        |
| text-sm focus:outline-none focus:ring-2 focus:ring-\[#0E7490\]\" /\>  |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| {error && \<p className=\"text-red-500 text-sm\"\>{error}\</p\>}      |
|                                                                       |
| \<button onClick={handleStep1} disabled={loading}                     |
|                                                                       |
| className=\"w-full bg-\[#0E7490\] text-white py-2 rounded-lg text-sm  |
| font-medium hover:bg-\[#0A5A6E\] disabled:opacity-50                  |
| transition-colors\"\>                                                 |
|                                                                       |
| {loading ? \'Creating account\...\' : \'Continue\'}                   |
|                                                                       |
| \</button\>                                                           |
|                                                                       |
| \<p className=\"text-center text-sm text-gray-500\"\>Already have an  |
| account? \<Link href=\"/auth/login\" className=\"text-\[#0E7490\]     |
| hover:underline\"\>Sign in\</Link\>\</p\>                             |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| ) : (                                                                 |
|                                                                       |
| \<div className=\"bg-white rounded-xl shadow-sm border                |
| border-gray-200 p-6 space-y-4\"\>                                     |
|                                                                       |
| \<p className=\"text-sm text-gray-600 text-center\"\>Tell us about    |
| yourself so we can personalise your experience.\</p\>                 |
|                                                                       |
| \<div\>                                                               |
|                                                                       |
| \<label className=\"block text-sm font-medium text-gray-700           |
| mb-1\"\>Professional Role\</label\>                                   |
|                                                                       |
| \<select value={role} onChange={e =\> setRole(e.target.value)}        |
|                                                                       |
| className=\"w-full px-3 py-2 border border-gray-300 rounded-lg        |
| text-sm focus:outline-none focus:ring-2 focus:ring-\[#0E7490\]\"\>    |
|                                                                       |
| \<option value=\"\"\>Select a role\</option\>                         |
|                                                                       |
| {ROLES.map(r =\> \<option key={r} value={r}\>{r}\</option\>)}         |
|                                                                       |
| \</select\>                                                           |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \<div\>                                                               |
|                                                                       |
| \<label className=\"block text-sm font-medium text-gray-700           |
| mb-1\"\>Primary Specialty\</label\>                                   |
|                                                                       |
| \<select value={specialty} onChange={e =\>                            |
| setSpecialty(e.target.value)}                                         |
|                                                                       |
| className=\"w-full px-3 py-2 border border-gray-300 rounded-lg        |
| text-sm focus:outline-none focus:ring-2 focus:ring-\[#0E7490\]\"\>    |
|                                                                       |
| \<option value=\"\"\>Select a specialty\</option\>                    |
|                                                                       |
| {SPECIALTIES.map(s =\> \<option key={s} value={s}\>{s}\</option\>)}   |
|                                                                       |
| \</select\>                                                           |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \<div\>                                                               |
|                                                                       |
| \<label className=\"block text-sm font-medium text-gray-700           |
| mb-1\"\>Preferred Region\</label\>                                    |
|                                                                       |
| \<select value={region} onChange={e =\> setRegion(e.target.value)}    |
|                                                                       |
| className=\"w-full px-3 py-2 border border-gray-300 rounded-lg        |
| text-sm focus:outline-none focus:ring-2 focus:ring-\[#0E7490\]\"\>    |
|                                                                       |
| \<option value=\"\"\>Select a region\</option\>                       |
|                                                                       |
| {REGIONS.map(r =\> \<option key={r} value={r}\>{r}\</option\>)}       |
|                                                                       |
| \</select\>                                                           |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| {error && \<p className=\"text-red-500 text-sm\"\>{error}\</p\>}      |
|                                                                       |
| \<button onClick={handleStep2} disabled={loading \|\| !role}          |
|                                                                       |
| className=\"w-full bg-\[#0E7490\] text-white py-2 rounded-lg text-sm  |
| font-medium hover:bg-\[#0A5A6E\] disabled:opacity-50                  |
| transition-colors\"\>                                                 |
|                                                                       |
| {loading ? \'Saving\...\' : \'Complete Sign Up\'}                     |
|                                                                       |
| \</button\>                                                           |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| )}                                                                    |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**9.2 Login --- src/app/auth/login/page.tsx**

+-----------------------------------------------------------------------+
| // src/app/auth/login/page.tsx                                        |
|                                                                       |
| \'use client\'                                                        |
|                                                                       |
| import { useState } from \'react\'                                    |
|                                                                       |
| import { useAuth } from \'@/hooks/useAuth\'                           |
|                                                                       |
| import Link from \'next/link\'                                        |
|                                                                       |
| export default function LoginPage() {                                 |
|                                                                       |
| const { signIn } = useAuth()                                          |
|                                                                       |
| const \[email, setEmail\] = useState(\'\')                            |
|                                                                       |
| const \[password, setPassword\] = useState(\'\')                      |
|                                                                       |
| const \[error, setError\] = useState(\'\')                            |
|                                                                       |
| const \[loading, setLoading\] = useState(false)                       |
|                                                                       |
| const handleLogin = async () =\> {                                    |
|                                                                       |
| setLoading(true); setError(\'\')                                      |
|                                                                       |
| const { error } = await signIn(email, password)                       |
|                                                                       |
| if (error) { setError(error.message) }                                |
|                                                                       |
| setLoading(false)                                                     |
|                                                                       |
| // Middleware will redirect authenticated users to /conferences       |
| automatically                                                         |
|                                                                       |
| }                                                                     |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<div className=\"max-w-md mx-auto mt-16\"\>                          |
|                                                                       |
| \<h1 className=\"text-2xl font-bold text-\[#1B2845\] text-center      |
| mb-6\"\>Welcome back\</h1\>                                           |
|                                                                       |
| \<div className=\"bg-white rounded-xl shadow-sm border                |
| border-gray-200 p-6 space-y-4\"\>                                     |
|                                                                       |
| \<div\>                                                               |
|                                                                       |
| \<label className=\"block text-sm font-medium text-gray-700           |
| mb-1\"\>Email\</label\>                                               |
|                                                                       |
| \<input type=\"email\" value={email} onChange={e =\>                  |
| setEmail(e.target.value)}                                             |
|                                                                       |
| className=\"w-full px-3 py-2 border border-gray-300 rounded-lg        |
| text-sm focus:outline-none focus:ring-2 focus:ring-\[#0E7490\]\" /\>  |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \<div\>                                                               |
|                                                                       |
| \<label className=\"block text-sm font-medium text-gray-700           |
| mb-1\"\>Password\</label\>                                            |
|                                                                       |
| \<input type=\"password\" value={password} onChange={e =\>            |
| setPassword(e.target.value)}                                          |
|                                                                       |
| className=\"w-full px-3 py-2 border border-gray-300 rounded-lg        |
| text-sm focus:outline-none focus:ring-2 focus:ring-\[#0E7490\]\" /\>  |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| {error && \<p className=\"text-red-500 text-sm\"\>{error}\</p\>}      |
|                                                                       |
| \<button onClick={handleLogin} disabled={loading}                     |
|                                                                       |
| className=\"w-full bg-\[#0E7490\] text-white py-2 rounded-lg text-sm  |
| font-medium hover:bg-\[#0A5A6E\] disabled:opacity-50                  |
| transition-colors\"\>                                                 |
|                                                                       |
| {loading ? \'Signing in\...\' : \'Sign In\'}                          |
|                                                                       |
| \</button\>                                                           |
|                                                                       |
| \<p className=\"text-center text-sm text-gray-500\"\>Don\'t have an   |
| account? \<Link href=\"/auth/signup\" className=\"text-\[#0E7490\]    |
| hover:underline\"\>Sign up\</Link\>\</p\>                             |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**9.3 Verify & Auth Callback**

+-----------------------------------------------------------------------+
| // src/app/auth/verify/page.tsx                                       |
|                                                                       |
| export default function VerifyPage() {                                |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<div className=\"max-w-md mx-auto mt-16 text-center\"\>              |
|                                                                       |
| \<div className=\"bg-white rounded-xl shadow-sm border                |
| border-gray-200 p-8\"\>                                               |
|                                                                       |
| \<div className=\"text-5xl mb-4\"\>✉️\</div\>                         |
|                                                                       |
| \<h1 className=\"text-xl font-bold text-\[#1B2845\] mb-2\"\>Check     |
| your email\</h1\>                                                     |
|                                                                       |
| \<p className=\"text-gray-500 text-sm\"\>We\'ve sent a verification   |
| link to your email address. Click the link to verify your account and |
| get started.\</p\>                                                    |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

+-----------------------------------------------------------------------+
| // src/app/auth/callback/route.ts                                     |
|                                                                       |
| // This file is REQUIRED by Supabase auth. Do not modify the logic.   |
|                                                                       |
| import { NextResponse } from \'next/server\'                          |
|                                                                       |
| import type { NextRequest } from \'next/server\'                      |
|                                                                       |
| import { createServerClient } from \'@supabase/nextjs\'               |
|                                                                       |
| export async function GET(request: NextRequest) {                     |
|                                                                       |
| const requestUrl = new URL(request.url)                               |
|                                                                       |
| const code = requestUrl.searchParams.get(\'code\')                    |
|                                                                       |
| if (code) {                                                           |
|                                                                       |
| const supabase = createServerClient(                                  |
|                                                                       |
| process.env.NEXT_PUBLIC_SUPABASE_URL!,                                |
|                                                                       |
| process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,                           |
|                                                                       |
| { cookies: {                                                          |
|                                                                       |
| getAll() { return request.cookies.getAll() },                         |
|                                                                       |
| setAll(cookiesToSet) {                                                |
|                                                                       |
| const response = NextResponse.redirect(new URL(\'/conferences\',      |
| requestUrl))                                                          |
|                                                                       |
| cookiesToSet.forEach(({ name, value, options }) =\>                   |
| response.cookies.set(name, value, options))                           |
|                                                                       |
| },                                                                    |
|                                                                       |
| }}                                                                    |
|                                                                       |
| )                                                                     |
|                                                                       |
| await supabase.auth.exchangeCodeForSession(code)                      |
|                                                                       |
| }                                                                     |
|                                                                       |
| return NextResponse.redirect(new URL(\'/conferences\', requestUrl))   |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**10. Conference Directory**

**10.1 Sub-Components**

**CPDBadge --- src/components/conferences/CPDBadge.tsx**

+-----------------------------------------------------------------------+
| // src/components/conferences/CPDBadge.tsx                            |
|                                                                       |
| interface CPDBadgeProps { accredited: boolean; points: number \| null |
| }                                                                     |
|                                                                       |
| export function CPDBadge({ accredited, points }: CPDBadgeProps) {     |
|                                                                       |
| if (accredited) {                                                     |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<span className=\"inline-flex items-center gap-1 bg-green-100        |
| text-green-700 text-xs font-semibold px-2.5 py-0.5 rounded-full\"\>   |
|                                                                       |
| \<span\>✓\</span\> CPD {points ? \`--- \${points} pts\` :             |
| \'Accredited\'}                                                       |
|                                                                       |
| \</span\>                                                             |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<span className=\"inline-flex items-center bg-gray-100 text-gray-500 |
| text-xs font-medium px-2.5 py-0.5 rounded-full\"\>                    |
|                                                                       |
| No CPD                                                                |
|                                                                       |
| \</span\>                                                             |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**SaveButton --- src/components/ui/SaveButton.tsx**

+-----------------------------------------------------------------------+
| // src/components/ui/SaveButton.tsx                                   |
|                                                                       |
| \'use client\'                                                        |
|                                                                       |
| import { useSaved } from \'@/hooks/useSaved\'                         |
|                                                                       |
| interface SaveButtonProps { conferenceId: number }                    |
|                                                                       |
| export function SaveButton({ conferenceId }: SaveButtonProps) {       |
|                                                                       |
| const { isSaved, toggleSave } = useSaved()                            |
|                                                                       |
| const saved = isSaved(conferenceId)                                   |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<button onClick={() =\> toggleSave(conferenceId)}                    |
|                                                                       |
| className={\`text-sm flex items-center gap-1.5 px-3 py-1.5 rounded-lg |
| border transition-colors \${                                          |
|                                                                       |
| saved ? \'bg-\[#0E7490\] text-white border-\[#0E7490\]\' : \'bg-white |
| text-gray-600 border-gray-300 hover:border-\[#0E7490\]                |
| hover:text-\[#0E7490\]\'                                              |
|                                                                       |
| }\`}\>                                                                |
|                                                                       |
| \<span\>{saved ? \'♥\' : \'♡\'}\</span\>                              |
|                                                                       |
| {saved ? \'Saved\' : \'Save\'}                                        |
|                                                                       |
| \</button\>                                                           |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**ConferenceCard --- src/components/conferences/ConferenceCard.tsx**

+-----------------------------------------------------------------------+
| // src/components/conferences/ConferenceCard.tsx                      |
|                                                                       |
| import Link from \'next/link\'                                        |
|                                                                       |
| import { CPDBadge } from \'@/components/conferences/CPDBadge\'        |
|                                                                       |
| import { SaveButton } from \'@/components/ui/SaveButton\'             |
|                                                                       |
| import type { Conference, PricingTier } from \'@/lib/types\'          |
|                                                                       |
| interface ConferenceCardProps { conference: Conference; tiers:        |
| PricingTier\[\] }                                                     |
|                                                                       |
| export function ConferenceCard({ conference: c, tiers }:              |
| ConferenceCardProps) {                                                |
|                                                                       |
| const minPrice = tiers.length ? Math.min(\...tiers.map(t =\>          |
| t.price_gbp)) : null                                                  |
|                                                                       |
| const maxPrice = tiers.length ? Math.max(\...tiers.map(t =\>          |
| t.price_gbp)) : null                                                  |
|                                                                       |
| const priceLabel = minPrice !== null ? (minPrice === maxPrice ?       |
| \`£\${minPrice}\` : \`£\${minPrice} -- £\${maxPrice}\`) : \'Price     |
| TBC\'                                                                 |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<div className=\"bg-white rounded-xl border border-gray-200          |
| shadow-sm hover:shadow-md transition-shadow p-5 flex flex-col         |
| gap-3\"\>                                                             |
|                                                                       |
| \<div className=\"flex justify-between items-start\"\>                |
|                                                                       |
| \<span className=\"text-xs font-semibold text-\[#0E7490\] uppercase   |
| tracking-wide\"\>{c.specialty \|\| \'General\'}\</span\>              |
|                                                                       |
| \<CPDBadge accredited={c.cpd_accredited} points={c.cpd_points} /\>    |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \<Link href={\`/conferences/\${c.id}\`}\>                             |
|                                                                       |
| \<h3 className=\"font-bold text-\[#1B2845\] hover:text-\[#0E7490\]    |
| transition-colors text-base                                           |
| leading-snug\"\>{c.conference_name}\</h3\>                            |
|                                                                       |
| \</Link\>                                                             |
|                                                                       |
| \<div className=\"text-sm text-gray-500 space-y-1\"\>                 |
|                                                                       |
| {c.start_date && \<p\>📅 {new                                         |
| Date(c.start_date).toLocaleDateString(\'en-GB\', { day:\'numeric\',   |
| month:\'long\', year:\'numeric\' })}{c.end_date && c.end_date !==     |
| c.start_date ? \` -- \${new                                           |
| Date(c.end_date).toLocaleDateString(\'en-GB\', {day:\'numeric\',      |
| month:\'long\'})}\` : \'\'}\</p\>}                                    |
|                                                                       |
| {c.venue_name && \<p\>📍 {c.venue_name}{c.city ? \`, \${c.city}\` :   |
| \'\'}\</p\>}                                                          |
|                                                                       |
| \<p\>💷 {priceLabel}\</p\>                                            |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \<div className=\"mt-auto pt-2 flex justify-between items-center\"\>  |
|                                                                       |
| \<Link href={\`/conferences/\${c.id}\`} className=\"text-sm           |
| text-\[#0E7490\] font-medium hover:underline\"\>View details          |
| →\</Link\>                                                            |
|                                                                       |
| \<SaveButton conferenceId={c.id} /\>                                  |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**10.2 Filter Panel --- src/components/conferences/FilterPanel.tsx**

+-----------------------------------------------------------------------+
| // src/components/conferences/FilterPanel.tsx                         |
|                                                                       |
| \'use client\'                                                        |
|                                                                       |
| import type { Filters } from \'@/hooks/useConferences\'               |
|                                                                       |
| const SPECIALTIES = \[\'All\',\'Cardiology\',\'General                |
| Practice\',\'Orthopaedics\',\'Surgery\',\'Emergency Medicine\',       |
|                                                                       |
| \'Neurology\',\'Oncology\'                                            |
| ,\'Paediatrics\',\'Psychiatry\',\'Radiology\',\'Nursing\',\'Other\'\] |
|                                                                       |
| const REGIONS = \[\'All\',\'London\',\'South East\',\'South           |
| West\',\'East of England\',\'Midlands\',                              |
|                                                                       |
| \'North East\',\'North                                                |
| West\',\'Yorkshire\',\'Wales\',\'Scotland\',\'Northern Ireland\'\]    |
|                                                                       |
| const PRICE_BANDS = \[                                                |
|                                                                       |
| { label: \'Any Price\', value: 0 },                                   |
|                                                                       |
| { label: \'Free\', value: 0.01 },                                     |
|                                                                       |
| { label: \'Under £100\', value: 100 },                                |
|                                                                       |
| { label: \'£100 -- £300\', value: 300 },                              |
|                                                                       |
| { label: \'£300 -- £500\', value: 500 },                              |
|                                                                       |
| { label: \'£500+\', value: 99999 },                                   |
|                                                                       |
| \]                                                                    |
|                                                                       |
| interface FilterPanelProps { filters: Filters; setFilters: (f:        |
| Filters) =\> void }                                                   |
|                                                                       |
| export function FilterPanel({ filters, setFilters }:                  |
| FilterPanelProps) {                                                   |
|                                                                       |
| const update = (key: keyof Filters, value: any) =\> setFilters({      |
| \...filters, \[key\]: value })                                        |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<div className=\"bg-white rounded-xl border border-gray-200          |
| shadow-sm p-5 space-y-5\"\>                                           |
|                                                                       |
| \<h2 className=\"font-bold text-\[#1B2845\]                           |
| text-base\"\>Filters\</h2\>                                           |
|                                                                       |
| {/\* Specialty \*/}                                                   |
|                                                                       |
| \<div\>                                                               |
|                                                                       |
| \<label className=\"block text-sm font-medium text-gray-700           |
| mb-2\"\>Specialty\</label\>                                           |
|                                                                       |
| \<div className=\"flex flex-wrap gap-2\"\>                            |
|                                                                       |
| {SPECIALTIES.map(s =\> (                                              |
|                                                                       |
| \<button key={s} onClick={() =\> update(\'specialty\', s === \'All\'  |
| ? \'\' : s)}                                                          |
|                                                                       |
| className={\`text-xs px-3 py-1 rounded-full border transition-colors  |
| \${                                                                   |
|                                                                       |
| (s === \'All\' && !filters.specialty) \|\| filters.specialty === s    |
|                                                                       |
| ? \'bg-\[#0E7490\] text-white border-\[#0E7490\]\'                    |
|                                                                       |
| : \'bg-white text-gray-600 border-gray-300 hover:border-\[#0E7490\]\' |
|                                                                       |
| }\`}\>{s}\</button\>                                                  |
|                                                                       |
| ))}                                                                   |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| {/\* Region \*/}                                                      |
|                                                                       |
| \<div\>                                                               |
|                                                                       |
| \<label className=\"block text-sm font-medium text-gray-700           |
| mb-1\"\>Location\</label\>                                            |
|                                                                       |
| \<select value={filters.region} onChange={e =\> update(\'region\',    |
| e.target.value === \'All\' ? \'\' : e.target.value)}                  |
|                                                                       |
| className=\"w-full px-3 py-2 border border-gray-300 rounded-lg        |
| text-sm focus:outline-none focus:ring-2 focus:ring-\[#0E7490\]\"\>    |
|                                                                       |
| {REGIONS.map(r =\> \<option key={r} value={r === \'All\' ? \'\' :     |
| r}\>{r}\</option\>)}                                                  |
|                                                                       |
| \</select\>                                                           |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| {/\* Price \*/}                                                       |
|                                                                       |
| \<div\>                                                               |
|                                                                       |
| \<label className=\"block text-sm font-medium text-gray-700           |
| mb-2\"\>Price Range\</label\>                                         |
|                                                                       |
| \<div className=\"flex flex-wrap gap-2\"\>                            |
|                                                                       |
| {PRICE_BANDS.map(p =\> (                                              |
|                                                                       |
| \<button key={p.label} onClick={() =\> update(\'maxPrice\', p.value)} |
|                                                                       |
| className={\`text-xs px-3 py-1 rounded-full border transition-colors  |
| \${                                                                   |
|                                                                       |
| filters.maxPrice === p.value ? \'bg-\[#0E7490\] text-white            |
| border-\[#0E7490\]\' : \'bg-white text-gray-600 border-gray-300       |
| hover:border-\[#0E7490\]\'                                            |
|                                                                       |
| }\`}\>{p.label}\</button\>                                            |
|                                                                       |
| ))}                                                                   |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| {/\* Reset \*/}                                                       |
|                                                                       |
| \<button onClick={() =\> setFilters({ specialty:\'\', region:\'\',    |
| maxPrice:0, searchTerm:\'\' })}                                       |
|                                                                       |
| className=\"text-sm text-\[#0E7490\] hover:underline\"\>Clear all     |
| filters\</button\>                                                    |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**10.3 Search Bar --- src/components/conferences/SearchBar.tsx**

+-----------------------------------------------------------------------+
| // src/components/conferences/SearchBar.tsx                           |
|                                                                       |
| \'use client\'                                                        |
|                                                                       |
| import { useState, useEffect } from \'react\'                         |
|                                                                       |
| interface SearchBarProps { value: string; onChange: (v: string) =\>   |
| void }                                                                |
|                                                                       |
| export function SearchBar({ value, onChange }: SearchBarProps) {      |
|                                                                       |
| const \[local, setLocal\] = useState(value)                           |
|                                                                       |
| // Debounce: only trigger onChange 400ms after the user stops typing  |
|                                                                       |
| useEffect(() =\> {                                                    |
|                                                                       |
| const timer = setTimeout(() =\> onChange(local), 400)                 |
|                                                                       |
| return () =\> clearTimeout(timer)                                     |
|                                                                       |
| }, \[local\])                                                         |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<div className=\"relative\"\>                                        |
|                                                                       |
| \<span className=\"absolute left-3 top-1/2 -translate-y-1/2           |
| text-gray-400\"\>🔍\</span\>                                          |
|                                                                       |
| \<input type=\"text\" value={local} onChange={e =\>                   |
| setLocal(e.target.value)}                                             |
|                                                                       |
| placeholder=\"Search by name, specialty, or location\...\"            |
|                                                                       |
| className=\"w-full pl-10 pr-4 py-2.5 border border-gray-300           |
| rounded-lg text-sm focus:outline-none focus:ring-2                    |
| focus:ring-\[#0E7490\] bg-white\" /\>                                 |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**10.4 Conference Directory Page --- src/app/conferences/page.tsx**

+-----------------------------------------------------------------------+
| // src/app/conferences/page.tsx                                       |
|                                                                       |
| \'use client\'                                                        |
|                                                                       |
| import { useConferences } from \'@/hooks/useConferences\'             |
|                                                                       |
| import { FilterPanel } from \'@/components/conferences/FilterPanel\'  |
|                                                                       |
| import { SearchBar } from \'@/components/conferences/SearchBar\'      |
|                                                                       |
| import { ConferenceCard } from                                        |
| \'@/components/conferences/ConferenceCard\'                           |
|                                                                       |
| export default function ConferencesPage() {                           |
|                                                                       |
| const { conferences, pricingMap, loading, filters, setFilters } =     |
| useConferences()                                                      |
|                                                                       |
| if (loading) {                                                        |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<div className=\"flex items-center justify-center h-64\"\>           |
|                                                                       |
| \<p className=\"text-gray-400 text-sm\"\>Loading                      |
| conferences\...\</p\>                                                 |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<div\>                                                               |
|                                                                       |
| {/\* Page header \*/}                                                 |
|                                                                       |
| \<div className=\"mb-6\"\>                                            |
|                                                                       |
| \<h1 className=\"text-2xl font-bold text-\[#1B2845\]\"\>Conference    |
| Directory\</h1\>                                                      |
|                                                                       |
| \<p className=\"text-gray-500 text-sm mt-1\"\>Browse upcoming medical |
| conferences and CPD opportunities across the UK\</p\>                 |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| {/\* Search \*/}                                                      |
|                                                                       |
| \<div className=\"mb-6\"\>                                            |
|                                                                       |
| \<SearchBar value={filters.searchTerm} onChange={v =\> setFilters({   |
| \...filters, searchTerm: v })} /\>                                    |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \<div className=\"flex flex-col lg:flex-row gap-6\"\>                 |
|                                                                       |
| {/\* Sidebar filters \*/}                                             |
|                                                                       |
| \<div className=\"w-full lg:w-72 shrink-0\"\>                         |
|                                                                       |
| \<FilterPanel filters={filters} setFilters={setFilters} /\>           |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| {/\* Conference grid \*/}                                             |
|                                                                       |
| \<div className=\"flex-1\"\>                                          |
|                                                                       |
| \<p className=\"text-sm text-gray-500 mb-4\"\>{conferences.length}    |
| conference{conferences.length !== 1 ? \'s\' : \'\'} found\</p\>       |
|                                                                       |
| {conferences.length === 0 ? (                                         |
|                                                                       |
| \<div className=\"bg-white rounded-xl border border-gray-200 p-8      |
| text-center\"\>                                                       |
|                                                                       |
| \<p className=\"text-gray-400 text-sm\"\>No conferences match your    |
| filters. Try adjusting your search.\</p\>                             |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| ) : (                                                                 |
|                                                                       |
| \<div className=\"grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3      |
| gap-4\"\>                                                             |
|                                                                       |
| {conferences.map(c =\> (                                              |
|                                                                       |
| \<ConferenceCard key={c.id} conference={c} tiers={pricingMap\[c.id\]  |
| \|\| \[\]} /\>                                                        |
|                                                                       |
| ))}                                                                   |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| )}                                                                    |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**11. Conference Detail Page**

**11.1 Pricing Table --- src/components/conferences/PricingTable.tsx**

+-----------------------------------------------------------------------+
| // src/components/conferences/PricingTable.tsx                        |
|                                                                       |
| import type { PricingTier } from \'@/lib/types\'                      |
|                                                                       |
| interface PricingTableProps { tiers: PricingTier\[\] }                |
|                                                                       |
| export function PricingTable({ tiers }: PricingTableProps) {          |
|                                                                       |
| if (tiers.length === 0) return \<p className=\"text-sm                |
| text-gray-400\"\>Pricing information not yet available.\</p\>         |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<div className=\"overflow-hidden rounded-lg border                   |
| border-gray-200\"\>                                                   |
|                                                                       |
| \<table className=\"w-full text-sm\"\>                                |
|                                                                       |
| \<thead className=\"bg-\[#1B2845\] text-white\"\>                     |
|                                                                       |
| \<tr\>                                                                |
|                                                                       |
| \<th className=\"text-left px-4 py-2.5 font-semibold\"\>Professional  |
| Level\</th\>                                                          |
|                                                                       |
| \<th className=\"text-right px-4 py-2.5 font-semibold\"\>Price\</th\> |
|                                                                       |
| \<th className=\"text-left px-4 py-2.5 font-semibold\"\>Notes\</th\>  |
|                                                                       |
| \</tr\>                                                               |
|                                                                       |
| \</thead\>                                                            |
|                                                                       |
| \<tbody\>                                                             |
|                                                                       |
| {tiers.map((t, i) =\> (                                               |
|                                                                       |
| \<tr key={t.id} className={i % 2 === 0 ? \'bg-white\' :               |
| \'bg-gray-50\'}\>                                                     |
|                                                                       |
| \<td className=\"px-4 py-2.5 text-gray-700                            |
| font-medium\"\>{t.tier_label}\</td\>                                  |
|                                                                       |
| \<td className=\"px-4 py-2.5 text-right text-gray-700                 |
| font-semibold\"\>£{t.price_gbp.toFixed(2)}\</td\>                     |
|                                                                       |
| \<td className=\"px-4 py-2.5 text-gray-400 text-xs\"\>                |
|                                                                       |
| {t.is_early_bird && t.early_bird_deadline ? (                         |
|                                                                       |
| \<span className=\"inline-block bg-amber-100 text-amber-700 px-2      |
| py-0.5 rounded\"\>                                                    |
|                                                                       |
| Early bird --- ends {new                                              |
| Date(t.early_bird_deadline).toLocaleDateString(\'en-GB\',             |
| {day:\'numeric\',month:\'long\'})}                                    |
|                                                                       |
| \</span\>                                                             |
|                                                                       |
| ) : \'---\'}                                                          |
|                                                                       |
| \</td\>                                                               |
|                                                                       |
| \</tr\>                                                               |
|                                                                       |
| ))}                                                                   |
|                                                                       |
| \</tbody\>                                                            |
|                                                                       |
| \</table\>                                                            |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**11.2 Detail Page --- src/app/conferences/\[id\]/page.tsx**

+-----------------------------------------------------------------------+
| // src/app/conferences/\[id\]/page.tsx                                |
|                                                                       |
| \'use client\'                                                        |
|                                                                       |
| import { useState, useEffect } from \'react\'                         |
|                                                                       |
| import { createSupabaseClient } from \'@/lib/supabase\'               |
|                                                                       |
| import { CPDBadge } from \'@/components/conferences/CPDBadge\'        |
|                                                                       |
| import { PricingTable } from                                          |
| \'@/components/conferences/PricingTable\'                             |
|                                                                       |
| import { SaveButton } from \'@/components/ui/SaveButton\'             |
|                                                                       |
| import type { Conference, PricingTier } from \'@/lib/types\'          |
|                                                                       |
| import Link from \'next/link\'                                        |
|                                                                       |
| export default function ConferenceDetailPage({ params }: { params: {  |
| id: string } }) {                                                     |
|                                                                       |
| const \[conference, setConference\] = useState\<Conference \|         |
| null\>(null)                                                          |
|                                                                       |
| const \[tiers, setTiers\] = useState\<PricingTier\[\]\>(\[\])         |
|                                                                       |
| const \[loading, setLoading\] = useState(true)                        |
|                                                                       |
| const supabase = createSupabaseClient()                               |
|                                                                       |
| useEffect(() =\> {                                                    |
|                                                                       |
| async function fetch() {                                              |
|                                                                       |
| const { data: conf } = await                                          |
| supabase.from(\'conferences\').select(\'\*\').eq(\'id\',              |
| Number(params.id)).single()                                           |
|                                                                       |
| const { data: pricing } = await                                       |
| supabase.from(\'pricing_tiers\').select(\'\*\').eq(\'conference_id\', |
| Number(params.id))                                                    |
|                                                                       |
| if (conf) setConference(conf)                                         |
|                                                                       |
| if (pricing) setTiers(pricing)                                        |
|                                                                       |
| setLoading(false)                                                     |
|                                                                       |
| }                                                                     |
|                                                                       |
| fetch()                                                               |
|                                                                       |
| }, \[params.id\])                                                     |
|                                                                       |
| if (loading) return \<div className=\"flex items-center               |
| justify-center h-64\"\>\<p className=\"text-gray-400                  |
| text-sm\"\>Loading\...\</p\>\</div\>                                  |
|                                                                       |
| if (!conference) return \<div className=\"text-center mt-16\"\>\<p    |
| className=\"text-gray-400\"\>Conference not found.\</p\>\<Link        |
| href=\"/conferences\" className=\"text-\[#0E7490\] text-sm mt-2 block |
| hover:underline\"\>← Back to directory\</Link\>\</div\>               |
|                                                                       |
| const c = conference                                                  |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<div className=\"max-w-3xl mx-auto\"\>                               |
|                                                                       |
| \<Link href=\"/conferences\" className=\"text-sm text-\[#0E7490\]     |
| hover:underline mb-4 block\"\>← Back to directory\</Link\>            |
|                                                                       |
| \<div className=\"bg-white rounded-xl border border-gray-200          |
| shadow-sm p-6 space-y-6\"\>                                           |
|                                                                       |
| {/\* Header \*/}                                                      |
|                                                                       |
| \<div className=\"flex justify-between items-start flex-wrap          |
| gap-3\"\>                                                             |
|                                                                       |
| \<div\>                                                               |
|                                                                       |
| \<span className=\"text-xs font-semibold text-\[#0E7490\] uppercase   |
| tracking-wide\"\>{c.specialty \|\| \'General\'}\</span\>              |
|                                                                       |
| \<h1 className=\"text-2xl font-bold text-\[#1B2845\]                  |
| mt-1\"\>{c.conference_name}\</h1\>                                    |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \<SaveButton conferenceId={c.id} /\>                                  |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| {/\* CPD badge \*/}                                                   |
|                                                                       |
| \<CPDBadge accredited={c.cpd_accredited} points={c.cpd_points} /\>    |
|                                                                       |
| {/\* Key details \*/}                                                 |
|                                                                       |
| \<div className=\"grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm\"\>   |
|                                                                       |
| {c.start_date && (\<div\>\<p className=\"text-gray-400                |
| font-medium\"\>Date\</p\>\<p className=\"text-gray-700\"\>{new        |
| Date(c.start_date).toLocaleDateString(\'en-GB\',{weekday:\            |
| 'long\',day:\'numeric\',month:\'long\',year:\'numeric\'})}{c.end_date |
| && c.end_date !== c.start_date ? \` -- \${new                         |
| Date(c.end_da                                                         |
| te).toLocaleDateString(\'en-GB\',{day:\'numeric\',month:\'long\'})}\` |
| : \'\'}\</p\>\</div\>)}                                               |
|                                                                       |
| {c.venue_name && (\<div\>\<p className=\"text-gray-400                |
| font-medium\"\>Venue\</p\>\<p                                         |
| className=\"text-gray-700\"\>{c.venue_name}{c.city ? \`, \${c.city}\` |
| : \'\'}{c.region ? \` (\${c.region})\` : \'\'}\</p\>\</div\>)}        |
|                                                                       |
| \<div\>\<p className=\"text-gray-400 font-medium\"\>Abstract          |
| Submissions\</p\>\<p className={\`font-semibold \${c.abstract_open ?  |
| \'text-green-600\' : \'text-gray-500\'}\`}\>{c.abstract_open ?        |
| \'Open\' : \'Closed\'}{c.abstract_open && c.abstract_deadline ? \`    |
| --- deadline \${new                                                   |
| Date(c.abstract_deadli                                                |
| ne).toLocaleDateString(\'en-GB\',{day:\'numeric\',month:\'long\'})}\` |
| : \'\'}\</p\>\</div\>                                                 |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| {/\* Description \*/}                                                 |
|                                                                       |
| {c.description && (\<div\>\<h2 className=\"font-bold text-\[#1B2845\] |
| text-base\"\>About\</h2\>\<p className=\"text-gray-600                |
| text-sm\"\>{c.description}\</p\>\</div\>)}                            |
|                                                                       |
| {/\* Pricing \*/}                                                     |
|                                                                       |
| \<div\>\<h2 className=\"font-bold text-\[#1B2845\] text-base          |
| mb-3\"\>Pricing\</h2\>\<PricingTable tiers={tiers} /\>\</div\>        |
|                                                                       |
| {/\* Book CTA \*/}                                                    |
|                                                                       |
| \<div className=\"bg-\[#F0F7FA\] rounded-lg p-4 text-center\"\>       |
|                                                                       |
| \<p className=\"text-sm text-gray-600 mb-3\"\>Ready to attend? Book   |
| directly on the organiser\'s website.\</p\>                           |
|                                                                       |
| {c.organiser_url ? (                                                  |
|                                                                       |
| \<a href={c.organiser_url} target=\"\_blank\" rel=\"noopener          |
| noreferrer\"                                                          |
|                                                                       |
| className=\"inline-block bg-\[#0E7490\] text-white px-6 py-2.5        |
| rounded-lg text-sm font-semibold hover:bg-\[#0A5A6E\]                 |
| transition-colors\"\>                                                 |
|                                                                       |
| Book on Official Site →                                               |
|                                                                       |
| \</a\>                                                                |
|                                                                       |
| ) : (                                                                 |
|                                                                       |
| \<p className=\"text-gray-400 text-sm\"\>Booking link coming          |
| soon.\</p\>                                                           |
|                                                                       |
| )}                                                                    |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**12. Saved Conferences Page**

+-----------------------------------------------------------------------+
| // src/app/saved/page.tsx                                             |
|                                                                       |
| \'use client\'                                                        |
|                                                                       |
| import { useState, useEffect } from \'react\'                         |
|                                                                       |
| import { createSupabaseClient } from \'@/lib/supabase\'               |
|                                                                       |
| import { ConferenceCard } from                                        |
| \'@/components/conferences/ConferenceCard\'                           |
|                                                                       |
| import type { Conference, PricingTier } from \'@/lib/types\'          |
|                                                                       |
| import { useAuth } from \'@/hooks/useAuth\'                           |
|                                                                       |
| export default function SavedPage() {                                 |
|                                                                       |
| const \[conferences, setConferences\] =                               |
| useState\<Conference\[\]\>(\[\])                                      |
|                                                                       |
| const \[pricingMap, setPricingMap\] = useState\<Record\<number,       |
| PricingTier\[\]\>\>({})                                               |
|                                                                       |
| const \[loading, setLoading\] = useState(true)                        |
|                                                                       |
| const { user } = useAuth()                                            |
|                                                                       |
| const supabase = createSupabaseClient()                               |
|                                                                       |
| useEffect(() =\> {                                                    |
|                                                                       |
| if (!user) return                                                     |
|                                                                       |
| async function fetchSaved() {                                         |
|                                                                       |
| // Get the user\'s saved conference IDs                               |
|                                                                       |
| const { data: saved } = await                                         |
| supabase.                                                             |
| from(\'saved_conferences\').select(\'conference_id\').eq(\'user_id\', |
| user.id)                                                              |
|                                                                       |
| if (!saved \|\| saved.length === 0) { setLoading(false); return }     |
|                                                                       |
| const ids = saved.map(s =\> s.conference_id)                          |
|                                                                       |
| // Fetch the full conference records                                  |
|                                                                       |
| const { data: confs } = await                                         |
| supabase.from(\'conferences\').select(\'\*\').in(\'id\', ids)         |
|                                                                       |
| if (confs) setConferences(confs)                                      |
|                                                                       |
| // Fetch pricing tiers for these conferences                          |
|                                                                       |
| const { data: tiers } = await                                         |
| supabase.from(\'pricing_tiers\').select(\'\*\').in(\'conference_id\', |
| ids)                                                                  |
|                                                                       |
| if (tiers) {                                                          |
|                                                                       |
| const map: Record\<number, PricingTier\[\]\> = {}                     |
|                                                                       |
| tiers.forEach(t =\> { if (!map\[t.conference_id\])                    |
| map\[t.conference_id\] = \[\]; map\[t.conference_id\].push(t) })      |
|                                                                       |
| setPricingMap(map)                                                    |
|                                                                       |
| }                                                                     |
|                                                                       |
| setLoading(false)                                                     |
|                                                                       |
| }                                                                     |
|                                                                       |
| fetchSaved()                                                          |
|                                                                       |
| }, \[user\])                                                          |
|                                                                       |
| if (loading) return \<div className=\"flex items-center               |
| justify-center h-64\"\>\<p className=\"text-gray-400                  |
| text-sm\"\>Loading\...\</p\>\</div\>                                  |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<div\>                                                               |
|                                                                       |
| \<h1 className=\"text-2xl font-bold text-\[#1B2845\] mb-2\"\>Saved    |
| Conferences\</h1\>                                                    |
|                                                                       |
| \<p className=\"text-gray-500 text-sm mb-6\"\>Your bookmarked         |
| conferences\</p\>                                                     |
|                                                                       |
| {conferences.length === 0 ? (                                         |
|                                                                       |
| \<div className=\"bg-white rounded-xl border border-gray-200 p-8      |
| text-center\"\>                                                       |
|                                                                       |
| \<p className=\"text-gray-400 text-sm\"\>You haven\'t saved any       |
| conferences yet. Browse the directory and click the save button on    |
| conferences you\'re interested in.\</p\>                              |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| ) : (                                                                 |
|                                                                       |
| \<div className=\"grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3      |
| gap-4\"\>                                                             |
|                                                                       |
| {conferences.map(c =\> \<ConferenceCard key={c.id} conference={c}     |
| tiers={pricingMap\[c.id\] \|\| \[\]} /\>)}                            |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| )}                                                                    |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**13. Notification Preferences (Settings Page)**

+-----------------------------------------------------------------------+
| // src/app/settings/page.tsx                                          |
|                                                                       |
| \'use client\'                                                        |
|                                                                       |
| import { useState, useEffect } from \'react\'                         |
|                                                                       |
| import { createSupabaseClient } from \'@/lib/supabase\'               |
|                                                                       |
| import { useAuth } from \'@/hooks/useAuth\'                           |
|                                                                       |
| import type { NotificationPreferences } from \'@/lib/types\'          |
|                                                                       |
| export default function SettingsPage() {                              |
|                                                                       |
| const { user } = useAuth()                                            |
|                                                                       |
| const supabase = createSupabaseClient()                               |
|                                                                       |
| const \[prefs, setPrefs\] = useState\<NotificationPreferences \|      |
| null\>(null)                                                          |
|                                                                       |
| const \[loading, setLoading\] = useState(true)                        |
|                                                                       |
| const \[saved, setSaved\] = useState(false)                           |
|                                                                       |
| useEffect(() =\> {                                                    |
|                                                                       |
| if (!user) return                                                     |
|                                                                       |
| async function fetchPrefs() {                                         |
|                                                                       |
| const { data } = await                                                |
| supab                                                                 |
| ase.from(\'notification_preferences\').select(\'\*\').eq(\'user_id\', |
| user.id).single()                                                     |
|                                                                       |
| if (data) setPrefs(data)                                              |
|                                                                       |
| setLoading(false)                                                     |
|                                                                       |
| }                                                                     |
|                                                                       |
| fetchPrefs()                                                          |
|                                                                       |
| }, \[user\])                                                          |
|                                                                       |
| const handleSave = async () =\> {                                     |
|                                                                       |
| if (!prefs \|\| !user) return                                         |
|                                                                       |
| await supabase.from(\'notification_preferences\').update({            |
|                                                                       |
| new_event_alerts: prefs.new_event_alerts,                             |
|                                                                       |
| deadline_reminders: prefs.deadline_reminders,                         |
|                                                                       |
| notification_channel: prefs.notification_channel,                     |
|                                                                       |
| digest_frequency: prefs.digest_frequency                              |
|                                                                       |
| }).eq(\'user_id\', user.id)                                           |
|                                                                       |
| setSaved(true)                                                        |
|                                                                       |
| setTimeout(() =\> setSaved(false), 3000)                              |
|                                                                       |
| }                                                                     |
|                                                                       |
| if (loading) return \<div className=\"flex items-center               |
| justify-center h-64\"\>\<p className=\"text-gray-400                  |
| text-sm\"\>Loading\...\</p\>\</div\>                                  |
|                                                                       |
| if (!prefs) return \<p className=\"text-gray-400\"\>Could not load    |
| preferences.\</p\>                                                    |
|                                                                       |
| const toggle = (key: \'new_event_alerts\' \| \'deadline_reminders\')  |
| =\>                                                                   |
|                                                                       |
| setPrefs(p =\> p ? { \...p, \[key\]: !p\[key\] } : p)                 |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<div className=\"max-w-2xl mx-auto\"\>                               |
|                                                                       |
| \<h1 className=\"text-2xl font-bold text-\[#1B2845\]                  |
| mb-6\"\>Notification Settings\</h1\>                                  |
|                                                                       |
| \<div className=\"bg-white rounded-xl border border-gray-200          |
| shadow-sm p-6 space-y-6\"\>                                           |
|                                                                       |
| {/\* Alert toggles \*/}                                               |
|                                                                       |
| \<div className=\"space-y-4\"\>                                       |
|                                                                       |
| \<h2 className=\"font-bold text-\[#1B2845\]                           |
| text-base\"\>Alerts\</h2\>                                            |
|                                                                       |
| {\[                                                                   |
|                                                                       |
| { key: \'new_event_alerts\' as const, label: \'New event alerts\',    |
| desc: \'Be notified when new conferences matching your specialty are  |
| added\' },                                                            |
|                                                                       |
| { key: \'deadline_reminders\' as const, label: \'Deadline             |
| reminders\', desc: \'Get reminders for abstract submission and        |
| early-bird registration deadlines on saved conferences\' },           |
|                                                                       |
| \].map(item =\> (                                                     |
|                                                                       |
| \<div key={item.key} className=\"flex items-start justify-between\"\> |
|                                                                       |
| \<div\>                                                               |
|                                                                       |
| \<p className=\"text-sm font-medium                                   |
| text-gray-700\"\>{item.label}\</p\>                                   |
|                                                                       |
| \<p className=\"text-xs text-gray-400 mt-0.5\"\>{item.desc}\</p\>     |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \<button onClick={() =\> toggle(item.key)}                            |
|                                                                       |
| className={\`relative w-11 h-6 rounded-full transition-colors         |
| \${prefs\[item.key\] ? \'bg-\[#0E7490\]\' : \'bg-gray-300\'}\`}\>     |
|                                                                       |
| \<span className={\`absolute top-0.5 left-0.5 w-5 h-5 bg-white        |
| rounded-full shadow transition-transform \${prefs\[item.key\] ?       |
| \'translate-x-5\' : \'\'}\`} /\>                                      |
|                                                                       |
| \</button\>                                                           |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| ))}                                                                   |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| {/\* Channel \*/}                                                     |
|                                                                       |
| \<div\>                                                               |
|                                                                       |
| \<h2 className=\"font-bold text-\[#1B2845\] text-base                 |
| mb-2\"\>Notification Channel\</h2\>                                   |
|                                                                       |
| \<select value={prefs.notification_channel} onChange={e =\>           |
| setPrefs(p =\> p ? { \...p, notification_channel: e.target.value } :  |
| p)}                                                                   |
|                                                                       |
| className=\"w-full px-3 py-2 border border-gray-300 rounded-lg        |
| text-sm focus:outline-none focus:ring-2 focus:ring-\[#0E7490\]\"\>    |
|                                                                       |
| \<option value=\"email\"\>Email only\</option\>                       |
|                                                                       |
| \<option value=\"both\"\>Email and in-app\</option\>                  |
|                                                                       |
| \</select\>                                                           |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| {/\* Frequency \*/}                                                   |
|                                                                       |
| \<div\>                                                               |
|                                                                       |
| \<h2 className=\"font-bold text-\[#1B2845\] text-base mb-2\"\>Digest  |
| Frequency\</h2\>                                                      |
|                                                                       |
| \<select value={prefs.digest_frequency} onChange={e =\> setPrefs(p    |
| =\> p ? { \...p, digest_frequency: e.target.value } : p)}             |
|                                                                       |
| className=\"w-full px-3 py-2 border border-gray-300 rounded-lg        |
| text-sm focus:outline-none focus:ring-2 focus:ring-\[#0E7490\]\"\>    |
|                                                                       |
| \<option value=\"immediate\"\>Immediate\</option\>                    |
|                                                                       |
| \<option value=\"daily\"\>Daily digest\</option\>                     |
|                                                                       |
| \<option value=\"weekly\"\>Weekly digest\</option\>                   |
|                                                                       |
| \</select\>                                                           |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| {/\* Save button \*/}                                                 |
|                                                                       |
| \<button onClick={handleSave}                                         |
|                                                                       |
| className=\"w-full bg-\[#0E7490\] text-white py-2 rounded-lg text-sm  |
| font-medium hover:bg-\[#0A5A6E\] transition-colors\"\>                |
|                                                                       |
| Save Preferences                                                      |
|                                                                       |
| \</button\>                                                           |
|                                                                       |
| {saved && \<p className=\"text-green-600 text-sm                      |
| text-center\"\>Preferences saved successfully.\</p\>}                 |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**14. Homepage --- src/app/page.tsx**

The homepage is the landing page for users who are not yet logged in. It
introduces MedConf, explains what it does, and drives sign-ups.
Logged-in users are redirected to the conference directory by the
middleware.

+-----------------------------------------------------------------------+
| // src/app/page.tsx                                                   |
|                                                                       |
| import Link from \'next/link\'                                        |
|                                                                       |
| export default function HomePage() {                                  |
|                                                                       |
| return (                                                              |
|                                                                       |
| \<div className=\"text-center max-w-3xl mx-auto mt-20\"\>             |
|                                                                       |
| {/\* Hero \*/}                                                        |
|                                                                       |
| \<h1 className=\"text-4xl font-bold text-\[#1B2845\]                  |
| leading-tight\"\>                                                     |
|                                                                       |
| Find the right medical\<br /\>conferences for your career.            |
|                                                                       |
| \</h1\>                                                               |
|                                                                       |
| \<p className=\"text-gray-500 mt-4 text-lg\"\>                        |
|                                                                       |
| MedConf is the UK\'s single directory for medical conferences, talks, |
| and CPD opportunities.                                                |
|                                                                       |
| Search, filter, and save --- all in one place.                        |
|                                                                       |
| \</p\>                                                                |
|                                                                       |
| \<div className=\"mt-8 flex justify-center gap-4\"\>                  |
|                                                                       |
| \<Link href=\"/auth/signup\" className=\"bg-\[#0E7490\] text-white    |
| px-6 py-3 rounded-lg font-semibold hover:bg-\[#0A5A6E\]               |
| transition-colors\"\>Get Started Free\</Link\>                        |
|                                                                       |
| \<Link href=\"/auth/login\" className=\"border border-gray-300        |
| text-gray-700 px-6 py-3 rounded-lg font-semibold hover:bg-gray-50     |
| transition-colors\"\>Sign In\</Link\>                                 |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| {/\* Feature summary \*/}                                             |
|                                                                       |
| \<div className=\"mt-20 grid grid-cols-1 md:grid-cols-3 gap-8         |
| text-left\"\>                                                         |
|                                                                       |
| {\[                                                                   |
|                                                                       |
| { icon: \'🔍\', title: \'Browse & Filter\', desc: \'Filter            |
| conferences by specialty, location, price range, and CPD status. Find |
| what matters to you in seconds.\' },                                  |
|                                                                       |
| { icon: \'📋\', title: \'Full Details\', desc: \'See complete pricing |
| breakdowns, CPD points, abstract submission status, and venue         |
| information before you commit.\' },                                   |
|                                                                       |
| { icon: \'🔔\', title: \'Stay Informed\', desc: \'Get notified when   |
| new conferences in your specialty are added, and never miss an        |
| abstract submission deadline.\' },                                    |
|                                                                       |
| \].map(f =\> (                                                        |
|                                                                       |
| \<div key={f.title} className=\"bg-white rounded-xl border            |
| border-gray-200 p-6\"\>                                               |
|                                                                       |
| \<div className=\"text-2xl mb-3\"\>{f.icon}\</div\>                   |
|                                                                       |
| \<h3 className=\"font-bold text-\[#1B2845\]\"\>{f.title}\</h3\>       |
|                                                                       |
| \<p className=\"text-gray-500 text-sm mt-1\"\>{f.desc}\</p\>          |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| ))}                                                                   |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| \</div\>                                                              |
|                                                                       |
| )                                                                     |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**15. Deployment & Testing**

**15.1 Local Development**

+-----------------------------------------------------------------------+
| \# Run the development server                                         |
|                                                                       |
| cd medconf-website                                                    |
|                                                                       |
| npm run dev                                                           |
|                                                                       |
| \# Open http://localhost:3000 in your browser                         |
+-----------------------------------------------------------------------+

**15.2 Deploying to Vercel**

Vercel deploys Next.js apps with zero configuration. Follow these steps:

1.  **Create a Vercel account.** Go to vercel.com and sign up with your
    GitHub account.

2.  **Push your code to GitHub.** Create a repository and push the
    medconf-website project.

3.  **Import into Vercel.** In the Vercel dashboard, click Import
    Project, select your GitHub repository, and click Deploy.

4.  **Set environment variables.** In the Vercel project settings, go to
    Environment Variables and add NEXT_PUBLIC_SUPABASE_URL and
    NEXT_PUBLIC_SUPABASE_ANON_KEY with your Supabase values.

5.  **Update Supabase auth URLs.** Go back to your Supabase dashboard,
    update the Site URL to your Vercel deployment URL (e.g.
    https://medconf-website.vercel.app), and add the same URL with
    /auth/callback to the Redirect URLs.

6.  **Redeploy.** Trigger a new deployment in Vercel (or push a new
    commit). The app is now live.

**15.3 Pre-Launch Testing Checklist**

1.  **Sign-up flow.** Register a new account, verify your email,
    complete the profile. Confirm you are redirected to the conference
    directory.

2.  **Login & logout.** Sign out, sign back in. Confirm the session
    persists on page refresh.

3.  **Route protection.** While logged out, try navigating directly to
    /conferences, /saved, and /settings. Confirm you are redirected to
    /auth/login each time.

4.  **Conference directory.** Confirm conferences populated by the
    scraper appear as cards. Verify the count, card layout, and CPD
    badges.

5.  **Filtering.** Test each filter (specialty, region, price)
    individually and in combination. Confirm the results update
    correctly. Test the search bar with keywords.

6.  **Detail page.** Click into a conference. Confirm all fields render
    --- dates, venue, pricing table, CPD badge, abstract status. Confirm
    the \'Book on Official Site\' button opens the organiser URL in a
    new tab.

7.  **Save & unsave.** Save a conference from the card and from the
    detail page. Navigate to /saved and confirm it appears. Unsave it
    and confirm it disappears.

8.  **Settings.** Toggle notification preferences, change channel and
    frequency, save. Refresh the page and confirm settings persisted.

9.  **Mobile responsiveness.** Open the app on a mobile device or use
    browser dev tools to simulate a mobile viewport. Confirm the layout
    adapts --- filters stack vertically, cards go single column,
    navigation remains usable.

+-----------------------------------------------------------------------+
| **Production readiness**                                              |
|                                                                       |
| Before going live, ensure your Supabase project is on a paid plan     |
| (the free tier has limitations on storage and active users), your     |
| environment variables are set correctly in Vercel, and your Supabase  |
| auth is configured with a production SMTP provider for reliable email |
| delivery.                                                             |
+-----------------------------------------------------------------------+
