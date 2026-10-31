// src/lib/community/types.ts
// Types for the Community Contributions layer. Mirrors the SQL contract in
// MISSION_BOARD_CONTRIBUTIONS.md §2 — keep the two in step.

export type ContributionKind = 'new_event' | 'add_info'

export type ContributionStatus =
  | 'pending'
  | 'needs_info'
  | 'published'
  | 'rejected'
  | 'merged'
  | 'expired'
  | 'hidden'

export type EnrichmentStatus = 'waiting' | 'fetched' | 'blocked' | 'failed' | 'skipped'

/** Columns allowed in `community_facts.field` (DB CHECK constraint). */
export const FACT_FIELD_LIST = [
  'start_date',
  'end_date',
  'start_time',
  'venue_name',
  'city',
  'region',
  'event_format',
  'abstract_deadline',
  'abstract_open',
  'abstract_deadline_note',
  'cpd_accredited',
  'cpd_points',
  'organiser_url',
  'booking_url',
  'description',
  'note',
] as const

export type FactField = (typeof FACT_FIELD_LIST)[number]

/** Per-tier shape inside a fees block (client payload). */
export interface FeeTierPayload {
  label: string
  price: number
  is_early_bird: boolean
  early_bird_deadline?: string
}

export interface FeesPayload {
  currency: string
  from_price?: number
  tiers: FeeTierPayload[]
  notes?: string
}

export interface AddInfoPayload {
  fields: Partial<Record<FactField, string | number | boolean>>
  fees?: FeesPayload
  note?: string
  evidence_url?: string
}

export interface NewEventPayload {
  conference_name: string
  event_type: 'conference' | 'workshop' | 'course'
  event_format: 'in_person' | 'online' | 'hybrid'
  is_flagship?: boolean
  start_date: string
  end_date?: string
  start_time?: string
  country: string
  region?: string
  city?: string
  venue_name?: string
  specialty: string
  description?: string
  organiser_url: string
  booking_url?: string
  cpd_accredited: boolean
  cpd_points?: number
  abstract_open: boolean
  abstract_deadline?: string
  abstract_deadline_note?: string
  fees?: FeesPayload
  note?: string
  evidence_url?: string
}

export interface Contribution {
  id: string
  user_id: string | null
  kind: ContributionKind
  conference_id: number | null
  status: ContributionStatus
  payload: AddInfoPayload | NewEventPayload
  enrichment: Record<string, { value: unknown; method: string; agrees: boolean | null }> | null
  enrichment_status: EnrichmentStatus
  enriched_at: string | null
  evidence_url: string | null
  note: string | null
  final_payload: AddInfoPayload | NewEventPayload | null
  moderator_id: string | null
  moderator_note: string | null
  reviewed_at: string | null
  created_at: string
  updated_at: string
}

/** A published community fact (`community_facts` row). */
export interface CommunityFact {
  id: string
  contribution_id: string
  conference_id: number
  field: FactField
  value: unknown
  is_published: boolean
  created_at: string
}

/** A published community fee tier (`community_tiers` row). */
export interface CommunityTier {
  id: string
  contribution_id: string
  conference_id: number
  tier_label: string
  price: number | string
  currency: string
  is_early_bird: boolean | null
  early_bird_deadline: string | null
  is_published: boolean
  created_at: string
}

/** Sections the AddInfoDialog can offer. */
export type AddInfoSection = 'dates' | 'venue' | 'fees' | 'abstracts' | 'cpd' | 'links' | 'note'
