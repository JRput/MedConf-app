// src/app/onboarding/page.tsx
//
// Two steps — specialty, then grade — down from the old 3-step wizard (name,
// role + specialty, institution/country/region). Still writes to
// `user_profiles` with the same columns the old wizard used (see
// supabase_schema.sql:177-199); the fields this version no longer collects
// (full_name, institution, country, region) are simply left out of the
// upsert payload so they keep their existing value (or the DB default) —
// Settings lets a user fill in their name afterwards.
//
// `specialty` now stores the canonical taxonomy parent SLUG (see
// ../../lib/taxonomy/specialties.ts) rather than a raw label string, so the
// dashboard's queryDirectory-based "Deadlines in {specialty}" /
// "New in {specialty}" tiles can filter on it directly. NOTE for whoever
// owns medconf-scraper/fire_specialty_alerts.py: that cron still does an
// exact `.ilike("specialty", profile.specialty)` against the raw
// `conferences.specialty` column — it will need to expand the slug via
// `rawValuesForParent` (same approach as directory-query.ts) to keep
// matching multi-word parents correctly; single-word parents whose slug
// happens to equal the raw label (e.g. "cardiology") still match today by
// ilike's case-insensitive equality, but that's incidental, not intended.
'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, ArrowRight, CheckCircle, Loader2 } from 'lucide-react'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'
import { SpecialtyCombobox } from '@/components/account/SpecialtyCombobox'
import { GradeSelect } from '@/components/account/GradeSelect'
import { Button } from '@/components/ui/button'

export default function OnboardingPage() {
  const { user, loading: authLoading } = useAuth()
  const router = useRouter()
  const supabase = createSupabaseClient()

  const [step, setStep] = useState<1 | 2>(1)
  const [specialtySlug, setSpecialtySlug] = useState<string | null>(null)
  const [grade, setGrade] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [loadingProfile, setLoadingProfile] = useState(true)

  useEffect(() => {
    if (authLoading) return
    if (!user) {
      router.push('/auth/login')
      return
    }

    supabase
      .from('user_profiles')
      .select('specialty, role, profile_completed_at')
      .eq('id', user.id)
      .maybeSingle()
      .then(({ data }) => {
        if (data?.profile_completed_at) {
          router.push('/dashboard')
          return
        }
        if (data?.specialty) setSpecialtySlug(data.specialty)
        if (data?.role) setGrade(data.role)
        setLoadingProfile(false)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, authLoading, router])

  const handleNext = () => {
    if (!specialtySlug) {
      setError('Please select your specialty')
      return
    }
    setError('')
    setStep(2)
  }

  const handleDone = async () => {
    if (!grade) {
      setError('Please select your grade')
      return
    }
    if (!user) return

    setSaving(true)
    setError('')

    const nowIso = new Date().toISOString()
    const { error: profileError } = await supabase.from('user_profiles').upsert(
      {
        id: user.id,
        email: user.email ?? '',
        role: grade,
        specialty: specialtySlug,
        profile_completed_at: nowIso,
        // Watermark for the specialty-alert cron — see the old wizard's
        // comment, carried over unchanged: stamping NOW() means a new user
        // is only alerted about events added after they joined.
        last_specialty_alert_at: nowIso,
      },
      { onConflict: 'id' }
    )

    if (profileError) {
      console.error('Profile save failed:', profileError)
      setError('Could not save your profile. Please try again.')
      setSaving(false)
      return
    }

    const { data: existingPrefs } = await supabase.from('notification_preferences').select('id').eq('id', user.id).maybeSingle()

    if (!existingPrefs) {
      await supabase.from('notification_preferences').insert({
        id: user.id,
        email_new_conferences: true,
        email_abstract_deadlines: true,
        email_price_changes: false,
        email_frequency: 'weekly',
      })
    }

    router.push('/dashboard')
  }

  if (authLoading || loadingProfile) {
    return (
      <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center">
        <Loader2 className="size-6 animate-spin text-fg-subtle" />
      </div>
    )
  }

  return (
    <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-8 flex items-center justify-center gap-3">
          {[1, 2].map((n, i) => (
            <div key={n} className="flex items-center gap-3">
              <div className={`size-2.5 rounded-full transition-colors ${step >= n ? 'bg-brand' : 'bg-border'}`} />
              {i < 1 && <div className={`h-0.5 w-12 transition-colors ${step > n ? 'bg-brand' : 'bg-border'}`} />}
            </div>
          ))}
        </div>

        <div className="mb-8 text-center">
          <h1 className="type-h1 text-fg-strong">{step === 1 ? 'What’s your specialty?' : 'What’s your grade?'}</h1>
          <p className="mt-1.5 type-body text-fg-muted">
            {step === 1 ? 'Step 1 of 2 — we use this to surface relevant events on your dashboard.' : 'Step 2 of 2 — almost done.'}
          </p>
        </div>

        <div className="space-y-5 rounded-lg border border-border bg-surface p-6">
          {step === 1 ? (
            <SpecialtyCombobox value={specialtySlug} onChange={setSpecialtySlug} />
          ) : (
            <GradeSelect value={grade} onChange={setGrade} />
          )}

          {error && <p className="text-[0.8125rem] text-danger-text">{error}</p>}

          <div className="flex gap-3">
            {step === 2 && (
              <Button type="button" variant="outline" onClick={() => setStep(1)} disabled={saving}>
                <ArrowLeft className="size-4" />
                Back
              </Button>
            )}
            {step === 1 ? (
              <Button type="button" className="flex-1" onClick={handleNext}>
                Continue
                <ArrowRight className="size-4" />
              </Button>
            ) : (
              <Button type="button" className="flex-1" onClick={handleDone} disabled={saving}>
                {saving ? <Loader2 className="size-4 animate-spin" /> : <CheckCircle className="size-4" />}
                {saving ? 'Saving…' : 'Done'}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
