// src/lib/types.ts

export interface Conference {
  id: number
  source_id: number | null
  source_url: string
  conference_name: string
  specialty: string | null
  start_date: string | null // YYYY-MM-DD
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

export interface PricingTier {
  id: number
  conference_id: number
  tier_label: string
  price_gbp: number
  is_early_bird: boolean
  early_bird_deadline: string | null
}

export interface UserProfile {
  id: string
  email: string
  role: string // e.g. Student, Consultant, Registrar, Nurse
  specialty: string | null
  preferred_region: string | null
}

export interface SavedConference {
  id: number
  user_id: string
  conference_id: number
  saved_at: string
}

export interface NotificationPreferences {
  id: number
  user_id: string
  new_event_alerts: boolean
  deadline_reminders: boolean
  notification_channel: string // 'email' | 'both'
  digest_frequency: string // 'immediate' | 'daily' | 'weekly'
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


