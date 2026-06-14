// src/app/onboarding/page.tsx
'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'
import {
  ArrowRight, ArrowLeft, User, Stethoscope, MapPin, Building2,
  Globe, CheckCircle, AlertCircle, Loader2,
} from 'lucide-react'

const ROLES = [
  'Medical Student', 'Foundation Doctor', 'Core Trainee', 'Registrar',
  'Fellow', 'Consultant', 'GP', 'Nurse', 'Allied Health', 'Other',
]

const SPECIALTIES = [
  'Cardiology', 'General Practice', 'Orthopaedics', 'General Surgery', 'Emergency Medicine',
  'Neurology', 'Oncology', 'Paediatrics', 'Psychiatry', 'Radiology', 'Anaesthetics',
  'Obstetrics & Gynaecology', 'Dermatology', 'Ophthalmology', 'ENT', 'Urology',
  'Gastroenterology', 'Respiratory Medicine', 'Rheumatology', 'Nursing', 'Other',
]

const UK_REGIONS = [
  'London', 'South East', 'South West', 'East of England', 'East Midlands',
  'West Midlands', 'North East', 'North West', 'Yorkshire & Humber',
  'Wales', 'Scotland', 'Northern Ireland',
]

const COUNTRIES = [
  'United Kingdom', 'Ireland', 'United States', 'Canada', 'Australia', 'New Zealand',
  'India', 'Pakistan', 'Nigeria', 'South Africa', 'Singapore', 'UAE', 'Other',
]

export default function OnboardingPage() {
  const { user, loading: authLoading } = useAuth()
  const router = useRouter()
  const supabase = createSupabaseClient()

  const [step, setStep] = useState(1)
  const [fullName, setFullName] = useState('')
  const [role, setRole] = useState('')
  const [specialty, setSpecialty] = useState('')
  const [institution, setInstitution] = useState('')
  const [country, setCountry] = useState('United Kingdom')
  const [region, setRegion] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [loadingProfile, setLoadingProfile] = useState(true)

  // Auth check + pre-fill from any existing partial profile
  useEffect(() => {
    if (authLoading) return
    if (!user) {
      router.push('/auth/login')
      return
    }

    const loadExisting = async () => {
      const { data } = await supabase
        .from('user_profiles')
        .select('full_name, role, specialty, region, institution, country, profile_completed_at')
        .eq('id', user.id)
        .single()

      if (data?.profile_completed_at) {
        router.push('/dashboard')
        return
      }

      if (data) {
        setFullName(data.full_name ?? '')
        setRole(data.role ?? '')
        setSpecialty(data.specialty ?? '')
        setRegion(data.region ?? '')
        setInstitution(data.institution ?? '')
        setCountry(data.country ?? 'United Kingdom')
      }
      setLoadingProfile(false)
    }

    loadExisting()
  }, [user, authLoading, router, supabase])

  const handleStep1 = (e: React.FormEvent) => {
    e.preventDefault()
    if (!fullName.trim()) {
      setError('Please enter your full name')
      return
    }
    setError('')
    setStep(2)
  }

  const handleStep2 = (e: React.FormEvent) => {
    e.preventDefault()
    if (!role) {
      setError('Please select your role')
      return
    }
    if (!specialty) {
      setError('Please select your primary specialty')
      return
    }
    setError('')
    setStep(3)
  }

  const handleStep3 = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!country) {
      setError('Please select a country')
      return
    }
    if (!user) return

    setSaving(true)
    setError('')

    // Stamp last_specialty_alert_at = NOW() so the daily specialty-alert
    // cron only notifies this user about events added AFTER they signed up.
    // Without this, a fresh user with Cardiology specialty would otherwise
    // get a giant "127 new Cardiology conferences" alert on the next run.
    const nowIso = new Date().toISOString()
    const profilePayload = {
      id: user.id,
      email: user.email ?? '',
      full_name: fullName.trim(),
      role,
      specialty,
      institution: institution.trim() || null,
      country,
      region: country === 'United Kingdom' ? (region || null) : null,
      profile_completed_at: nowIso,
      last_specialty_alert_at: nowIso,
    }

    // upsert covers both fresh signups and partial-profile users from the old flow
    const { error: profileError } = await supabase
      .from('user_profiles')
      .upsert(profilePayload, { onConflict: 'id' })

    if (profileError) {
      console.error('Profile save failed:', profileError)
      setError('Could not save your profile. Please try again.')
      setSaving(false)
      return
    }

    // Notification preferences — only insert if absent. Schema-matched columns.
    const { data: existingPrefs } = await supabase
      .from('notification_preferences')
      .select('id')
      .eq('id', user.id)
      .single()

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
      <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
      </div>
    )
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center px-4 py-12 bg-grid-pattern">
      <div className="fixed inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 -z-10" />
      <div className="fixed top-0 right-0 w-[600px] h-[600px] bg-cyan-500/10 rounded-full blur-3xl -z-10" />
      <div className="fixed bottom-0 left-0 w-[400px] h-[400px] bg-teal-500/10 rounded-full blur-3xl -z-10" />

      <div className="w-full max-w-md">
        <div className="flex items-center justify-center gap-3 mb-8">
          {[1, 2, 3].map((n, i) => (
            <div key={n} className="flex items-center gap-3">
              <div className={`w-3 h-3 rounded-full transition-all ${step >= n ? 'bg-cyan-400' : 'bg-slate-700'}`} />
              {i < 2 && <div className={`w-12 h-0.5 transition-all ${step > n ? 'bg-cyan-400' : 'bg-slate-700'}`} />}
            </div>
          ))}
        </div>

        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white font-display mb-2">
            {step === 1 && 'Welcome — what shall we call you?'}
            {step === 2 && 'About your work'}
            {step === 3 && 'Where are you based?'}
          </h1>
          <p className="text-slate-400">
            {step === 1 && 'Step 1 of 3'}
            {step === 2 && 'Step 2 of 3 — helps us recommend relevant conferences'}
            {step === 3 && 'Step 3 of 3 — almost done'}
          </p>
        </div>

        <div className="glass-card rounded-2xl p-8">
          {step === 1 && (
            <form onSubmit={handleStep1} className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  <User className="w-4 h-4 inline mr-2" />
                  Full name
                </label>
                <input
                  type="text"
                  value={fullName}
                  onChange={e => setFullName(e.target.value)}
                  placeholder="Dr Jai Rajput"
                  className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all"
                />
              </div>

              {error && (
                <div className="flex items-center gap-2 text-rose-400 text-sm bg-rose-500/10 border border-rose-500/20 rounded-lg px-4 py-3">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" />
                  {error}
                </div>
              )}

              <button
                type="submit"
                className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-cyan-500 to-teal-500 text-white py-3 rounded-xl font-semibold hover:from-cyan-400 hover:to-teal-400 transition-all shadow-lg shadow-cyan-500/25"
              >
                Continue
                <ArrowRight className="w-4 h-4" />
              </button>
            </form>
          )}

          {step === 2 && (
            <form onSubmit={handleStep2} className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  <User className="w-4 h-4 inline mr-2" />
                  Role
                </label>
                <select
                  value={role}
                  onChange={e => setRole(e.target.value)}
                  className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all appearance-none cursor-pointer"
                >
                  <option value="" className="bg-slate-800">Select your role</option>
                  {ROLES.map(r => <option key={r} value={r} className="bg-slate-800">{r}</option>)}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  <Stethoscope className="w-4 h-4 inline mr-2" />
                  Primary specialty
                </label>
                <select
                  value={specialty}
                  onChange={e => setSpecialty(e.target.value)}
                  className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all appearance-none cursor-pointer"
                >
                  <option value="" className="bg-slate-800">Select a specialty</option>
                  {SPECIALTIES.map(s => <option key={s} value={s} className="bg-slate-800">{s}</option>)}
                </select>
              </div>

              {error && (
                <div className="flex items-center gap-2 text-rose-400 text-sm bg-rose-500/10 border border-rose-500/20 rounded-lg px-4 py-3">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" />
                  {error}
                </div>
              )}

              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => setStep(1)}
                  className="flex items-center justify-center gap-2 px-4 py-3 border border-slate-700 rounded-xl text-slate-300 hover:bg-slate-800/50 transition-all"
                >
                  <ArrowLeft className="w-4 h-4" />
                  Back
                </button>
                <button
                  type="submit"
                  className="flex-1 flex items-center justify-center gap-2 bg-gradient-to-r from-cyan-500 to-teal-500 text-white py-3 rounded-xl font-semibold hover:from-cyan-400 hover:to-teal-400 transition-all shadow-lg shadow-cyan-500/25"
                >
                  Continue
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </form>
          )}

          {step === 3 && (
            <form onSubmit={handleStep3} className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  <Building2 className="w-4 h-4 inline mr-2" />
                  Institution <span className="text-slate-500 font-normal">(optional)</span>
                </label>
                <input
                  type="text"
                  value={institution}
                  onChange={e => setInstitution(e.target.value)}
                  placeholder="e.g. Guy's and St Thomas' NHS Trust"
                  className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  <Globe className="w-4 h-4 inline mr-2" />
                  Country
                </label>
                <select
                  value={country}
                  onChange={e => setCountry(e.target.value)}
                  className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all appearance-none cursor-pointer"
                >
                  {COUNTRIES.map(c => <option key={c} value={c} className="bg-slate-800">{c}</option>)}
                </select>
              </div>

              {country === 'United Kingdom' && (
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-2">
                    <MapPin className="w-4 h-4 inline mr-2" />
                    UK region <span className="text-slate-500 font-normal">(optional)</span>
                  </label>
                  <select
                    value={region}
                    onChange={e => setRegion(e.target.value)}
                    className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all appearance-none cursor-pointer"
                  >
                    <option value="" className="bg-slate-800">Select a region</option>
                    {UK_REGIONS.map(r => <option key={r} value={r} className="bg-slate-800">{r}</option>)}
                  </select>
                </div>
              )}

              {error && (
                <div className="flex items-center gap-2 text-rose-400 text-sm bg-rose-500/10 border border-rose-500/20 rounded-lg px-4 py-3">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" />
                  {error}
                </div>
              )}

              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => setStep(2)}
                  disabled={saving}
                  className="flex items-center justify-center gap-2 px-4 py-3 border border-slate-700 rounded-xl text-slate-300 hover:bg-slate-800/50 disabled:opacity-50 transition-all"
                >
                  <ArrowLeft className="w-4 h-4" />
                  Back
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="flex-1 flex items-center justify-center gap-2 bg-gradient-to-r from-cyan-500 to-teal-500 text-white py-3 rounded-xl font-semibold hover:from-cyan-400 hover:to-teal-400 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-cyan-500/25"
                >
                  {saving ? 'Saving…' : 'Complete setup'}
                  <CheckCircle className="w-4 h-4" />
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
