'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { createSupabaseClient } from '@/lib/supabase'
import { Loader2 } from 'lucide-react'

export default function SetupProfilePage() {
  const router = useRouter()
  const supabase = createSupabaseClient()
  const [status, setStatus] = useState<'loading' | 'creating' | 'error'>('loading')
  const [errorMessage, setErrorMessage] = useState('')

  useEffect(() => {
    const setupProfile = async () => {
      // #region agent log
      console.log('[DEBUG-B] Setup profile useEffect started');
      // #endregion
      
      try {
        // Get current user
        const { data: { user }, error: userError } = await supabase.auth.getUser()
        
        // #region agent log
        console.log('[DEBUG-C] After getUser:', {hasUser:!!user,userId:user?.id,hasError:!!userError,errorMsg:userError?.message});
        // #endregion
        
        if (userError || !user) {
          console.error('No user found:', userError)
          router.push('/auth/login')
          return
        }

        // Check if profile already exists
        const { data: existingProfile } = await supabase
          .from('user_profiles')
          .select('id')
          .eq('id', user.id)
          .single()

        // #region agent log
        console.log('[DEBUG-F] Existing profile check:', {hasExistingProfile:!!existingProfile,profileId:existingProfile?.id});
        // #endregion

        if (existingProfile) {
          // Profile already exists, redirect to conferences
          console.log('[DEBUG-F] Profile already exists, redirecting to conferences');
          router.push('/conferences')
          return
        }

        setStatus('creating')

        // Get pending profile data from localStorage
        const pendingProfileData = localStorage.getItem('pendingProfile')
        
        // #region agent log
        console.log('[DEBUG-D] LocalStorage data:', {hasPendingData:!!pendingProfileData,dataLength:pendingProfileData?.length,rawData:pendingProfileData});
        // #endregion
        
        if (!pendingProfileData) {
          // No pending profile data, redirect to conferences anyway
          console.log('[DEBUG-D] No pending profile data, redirecting to conferences');
          router.push('/conferences')
          return
        }

        const profileData = JSON.parse(pendingProfileData)
        
        // #region agent log
        console.log('[DEBUG-D] Parsed profile data:', {profileData:profileData});
        // #endregion

        // #region agent log
        console.log('[DEBUG-E] Before profile insert:', {userId:user.id,email:user.email,role:profileData.role,specialty:profileData.specialty,region:profileData.region});
        // #endregion
        
        // Create user profile
        const { error: profileError } = await supabase.from('user_profiles').insert({
          id: user.id,
          email: user.email || '',
          role: profileData.role || null,
          specialty: profileData.specialty || null,
          region: profileData.region || null
        })

        // #region agent log
        console.log('[DEBUG-E] After profile insert:', {hasError:!!profileError,errorMsg:profileError?.message,errorDetails:profileError?.details,errorCode:profileError?.code,errorHint:profileError?.hint});
        // #endregion

        if (profileError) {
          console.error('Profile creation error:', profileError)
          throw profileError
        }

        // Create default notification preferences
        const { error: notificationError } = await supabase.from('notification_preferences').insert({
          id: user.id,
          email_new_conferences: true,
          email_abstract_deadlines: true,
          email_price_changes: false,
          email_frequency: 'weekly'
        })

        if (notificationError) {
          console.error('Notification preferences error:', notificationError)
          // Don't throw here, as the main profile was created successfully
        }

        // Clear pending profile data
        localStorage.removeItem('pendingProfile')

        // Redirect to conferences
        router.push('/conferences')
      } catch (error) {
        console.error('Setup profile error:', error)
        setStatus('error')
        setErrorMessage('Failed to set up your profile. Please try again.')
        
        // Redirect to conferences after 3 seconds even on error
        setTimeout(() => {
          router.push('/conferences')
        }, 3000)
      }
    }

    setupProfile()
  }, [router, supabase])

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-grid-pattern">
      {/* Background gradient */}
      <div className="fixed inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 -z-10" />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-cyan-500/10 rounded-full blur-3xl -z-10" />

      <div className="w-full max-w-md text-center">
        <div className="glass-card rounded-2xl p-10">
          {status === 'loading' || status === 'creating' ? (
            <>
              <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-cyan-500/20 to-teal-500/20 border border-cyan-500/30 flex items-center justify-center">
                <Loader2 className="w-10 h-10 text-cyan-400 animate-spin" />
              </div>
              
              <h1 className="text-2xl font-bold text-white font-display mb-3">
                {status === 'loading' ? 'Verifying your email...' : 'Setting up your profile...'}
              </h1>
              
              <p className="text-slate-400 leading-relaxed">
                Please wait while we complete your registration.
              </p>
            </>
          ) : (
            <>
              <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-red-500/20 to-orange-500/20 border border-red-500/30 flex items-center justify-center">
                <span className="text-3xl">⚠️</span>
              </div>
              
              <h1 className="text-2xl font-bold text-white font-display mb-3">Setup Error</h1>
              
              <p className="text-slate-400 mb-4 leading-relaxed">
                {errorMessage}
              </p>
              
              <p className="text-sm text-slate-500">
                Redirecting you to the conferences page...
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

