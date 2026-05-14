// src/app/auth/signup/page.tsx
'use client'

import { useState } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { createSupabaseClient } from '@/lib/supabase'
import { ArrowRight, ArrowLeft, User, Stethoscope, MapPin, Mail, Lock, AlertCircle, CheckCircle } from 'lucide-react'

const ROLES = ['Medical Student', 'Foundation Doctor', 'Registrar', 'Consultant', 'GP', 'Nurse', 'Allied Health', 'Other']
const SPECIALTIES = [
  'Cardiology', 'General Practice', 'Orthopaedics', 'General Surgery', 'Emergency Medicine',
  'Neurology', 'Oncology', 'Paediatrics', 'Psychiatry', 'Radiology', 'Anaesthetics',
  'Obstetrics & Gynaecology', 'Dermatology', 'Ophthalmology', 'ENT', 'Urology', 
  'Gastroenterology', 'Respiratory Medicine', 'Rheumatology', 'Nursing', 'Other'
]
const REGIONS = [
  'London', 'South East', 'South West', 'East of England', 'East Midlands',
  'West Midlands', 'North East', 'North West', 'Yorkshire & Humber', 
  'Wales', 'Scotland', 'Northern Ireland'
]

export default function SignUpPage() {
  const { signUp } = useAuth()
  const router = useRouter()
  const supabase = createSupabaseClient()

  const [step, setStep] = useState(1)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('')
  const [specialty, setSpecialty] = useState('')
  const [region, setRegion] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleStep1 = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email || !password) {
      setError('Please fill in all fields')
      return
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }

    setLoading(true)
    setError('')
    
    const { error } = await signUp(email, password)
    
    if (error) { 
      setError(error.message)
      setLoading(false)
      return 
    }
    
    setLoading(false)
    setStep(2)
  }

  const handleStep2 = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!role) {
      setError('Please select your role')
      return
    }

    // Store profile data for after email verification
    if (typeof window !== 'undefined') {
      localStorage.setItem('pendingProfile', JSON.stringify({ role, specialty, region }))
    }

    // Redirect to verification page (profile will be created after email verification)
    router.push('/auth/verify')
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center px-4 py-12 bg-grid-pattern">
      {/* Background gradient */}
      <div className="fixed inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 -z-10" />
      <div className="fixed top-0 right-0 w-[600px] h-[600px] bg-cyan-500/10 rounded-full blur-3xl -z-10" />
      <div className="fixed bottom-0 left-0 w-[400px] h-[400px] bg-teal-500/10 rounded-full blur-3xl -z-10" />

      <div className="w-full max-w-md">
        {/* Progress indicator */}
        <div className="flex items-center justify-center gap-3 mb-8">
          <div className={`w-3 h-3 rounded-full transition-all ${step >= 1 ? 'bg-cyan-400' : 'bg-slate-700'}`} />
          <div className={`w-12 h-0.5 transition-all ${step >= 2 ? 'bg-cyan-400' : 'bg-slate-700'}`} />
          <div className={`w-3 h-3 rounded-full transition-all ${step >= 2 ? 'bg-cyan-400' : 'bg-slate-700'}`} />
        </div>

        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white font-display mb-2">
            {step === 1 ? 'Create your account' : 'Tell us about you'}
          </h1>
          <p className="text-slate-400">
            {step === 1 ? 'Start discovering medical conferences' : 'We\'ll personalise your experience'}
          </p>
        </div>

        <div className="glass-card rounded-2xl p-8">
          {step === 1 ? (
            <form onSubmit={handleStep1} className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Email address</label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-500" />
                  <input 
                    type="email" 
                    value={email} 
                    onChange={e => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="w-full pl-11 pr-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all" 
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Password</label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-500" />
                  <input 
                    type="password" 
                    value={password} 
                    onChange={e => setPassword(e.target.value)}
                    placeholder="Min. 8 characters"
                    className="w-full pl-11 pr-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all" 
                  />
                </div>
              </div>

              {error && (
                <div className="flex items-center gap-2 text-rose-400 text-sm bg-rose-500/10 border border-rose-500/20 rounded-lg px-4 py-3">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" />
                  {error}
                </div>
              )}

              <button 
                type="submit"
                disabled={loading}
                className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-cyan-500 to-teal-500 text-white py-3 rounded-xl font-semibold hover:from-cyan-400 hover:to-teal-400 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-cyan-500/25"
              >
                {loading ? 'Creating account...' : 'Continue'}
                <ArrowRight className="w-4 h-4" />
              </button>

              <p className="text-center text-sm text-slate-400">
                Already have an account?{' '}
                <Link href="/auth/login" className="text-cyan-400 hover:text-cyan-300 font-medium">
                  Sign in
                </Link>
              </p>
            </form>
          ) : (
            <form onSubmit={handleStep2} className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  <User className="w-4 h-4 inline mr-2" />
                  Professional Role
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
                  Primary Specialty
                </label>
                <select 
                  value={specialty} 
                  onChange={e => setSpecialty(e.target.value)}
                  className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all appearance-none cursor-pointer"
                >
                  <option value="" className="bg-slate-800">Select a specialty (optional)</option>
                  {SPECIALTIES.map(s => <option key={s} value={s} className="bg-slate-800">{s}</option>)}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  <MapPin className="w-4 h-4 inline mr-2" />
                  Preferred Region
                </label>
                <select 
                  value={region} 
                  onChange={e => setRegion(e.target.value)}
                  className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all appearance-none cursor-pointer"
                >
                  <option value="" className="bg-slate-800">Select a region (optional)</option>
                  {REGIONS.map(r => <option key={r} value={r} className="bg-slate-800">{r}</option>)}
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
                  disabled={loading || !role}
                  className="flex-1 flex items-center justify-center gap-2 bg-gradient-to-r from-cyan-500 to-teal-500 text-white py-3 rounded-xl font-semibold hover:from-cyan-400 hover:to-teal-400 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-cyan-500/25"
                >
                  {loading ? 'Saving...' : 'Complete Sign Up'}
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

