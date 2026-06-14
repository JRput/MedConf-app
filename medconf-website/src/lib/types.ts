// src/lib/types.ts

export type EventType = 'conference' | 'course'

export interface Conference {
  id: number
  source_id: number | null
  source_url: string
  conference_name: string
  specialty: string | null
  // 'conference' is the historical default; 'course' rows have child rows
  // in course_sessions for each scheduled run.
  event_type: EventType
  start_date: string | null // YYYY-MM-DD — for courses, this mirrors the
                            // SOONEST upcoming session for sort/list purposes
  end_date: string | null
  start_time: string | null // HH:MM:SS
  venue_name: string | null
  city: string | null
  region: string | null
  event_format: 'in_person' | 'online' | 'hybrid' | null
  is_sold_out: boolean
  cpd_accredited: boolean
  cpd_points: number | null
  abstract_open: boolean
  abstract_deadline: string | null
  organiser_url: string | null
  booking_url: string | null
  description: string | null
  archived: boolean
  created_at: string
  updated_at: string
}

export type AvailabilityStatus = 'available' | 'limited' | 'sold_out' | 'unknown'

export interface CourseSession {
  id: string
  course_id: number
  start_date: string // YYYY-MM-DD
  end_date: string | null
  start_time: string | null
  duration_text: string | null
  availability_status: AvailabilityStatus
  spots_left: number | null
  booking_url: string | null
  venue_name: string | null
  city: string | null
  region: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface PricingTier {
  id: number
  conference_id: number
  // NULL = the tier applies to the whole course (or to the conference).
  // Non-null = the tier is scoped to one specific course session.
  session_id: string | null
  tier_label: string
  price_gbp: number
  is_early_bird: boolean
  early_bird_deadline: string | null
}

export interface UserProfile {
  id: string
  email: string
  full_name: string | null
  role: string | null
  specialty: string | null
  region: string | null
  institution: string | null
  country: string
  profile_completed_at: string | null
  last_specialty_alert_at: string | null
  created_at: string
  updated_at: string
}

export interface SavedConference {
  id: number
  user_id: string
  conference_id: number
  saved_at: string
}

// Matches the actual notification_preferences columns in supabase_schema.sql.
export interface NotificationPreferences {
  id: string
  email_new_conferences: boolean
  email_abstract_deadlines: boolean
  email_price_changes: boolean
  email_frequency: string // 'immediate' | 'daily' | 'weekly'
  created_at: string
  updated_at: string
}

export type ReminderType = 'abstract_deadline' | 'conference_start' | 'registration_deadline'
export type ReminderStatus = 'scheduled' | 'sent' | 'cancelled'

export interface UserReminder {
  id: string
  user_id: string
  conference_id: number
  reminder_type: ReminderType
  lead_time_days: number
  target_date: string // YYYY-MM-DD
  scheduled_for: string // YYYY-MM-DD
  status: ReminderStatus
  sent_at: string | null
  created_at: string
  updated_at: string
}

export type NotificationType = 'reminder' | 'new_in_specialty' | 'conference_change' | 'system'

export interface NotificationItem {
  id: string
  user_id: string
  type: NotificationType
  title: string
  body: string | null
  conference_id: number | null
  reminder_id: string | null
  read_at: string | null
  created_at: string
}

// Scraper types
export interface ScraperSource {
  id: number
  source_name: string
  base_url: string
  extraction_instructions: string
  active: boolean
  last_scraped_at: string | null
  last_status: string
  // What the source primarily produces. Per-event extractors can override.
  default_event_type: 'conference' | 'course' | 'mixed'
  created_at: string
  updated_at: string
}

// Lightweight version exposed to the public frontend for filtering/badges.
// Pulled from `scraper_sources` via a public-read RLS policy (added by migration).
export interface SourceSummary {
  id: number
  source_name: string
  base_url: string
}

export interface ScraperLog {
  id: number
  source_id: number
  run_started_at: string
  run_ended_at: string | null
  status: string
  conferences_found: number
  conferences_inserted: number
  conferences_updated: number
  errors_encountered: number
  error_details: string | null
  created_at: string
}


