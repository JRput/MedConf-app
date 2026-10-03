// src/app/settings/page.tsx
'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Check, Loader2, LogOut } from 'lucide-react'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'
import { SPECIALTY_PARENTS, canonicalSpecialty } from '@/lib/taxonomy/specialties'
import { AccountContainer, AccountPageHeader, AccountSection } from '@/components/account/AccountPageHeader'
import { SpecialtyCombobox } from '@/components/account/SpecialtyCombobox'
import { GradeSelect } from '@/components/account/GradeSelect'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { ThemeToggle } from '@/components/theme/ThemeToggle'
import { toast } from 'sonner'

function toSpecialtySlug(raw: string | null): string | null {
  if (!raw) return null
  if (SPECIALTY_PARENTS.some((p) => p.slug === raw)) return raw
  return canonicalSpecialty(raw).parent
}

export default function SettingsPage() {
  const { user, signOut } = useAuth()
  const router = useRouter()
  const supabase = createSupabaseClient()

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [fullName, setFullName] = useState('')
  const [specialtySlug, setSpecialtySlug] = useState<string | null>(null)
  const [grade, setGrade] = useState<string | null>(null)

  useEffect(() => {
    if (!user) return
    supabase
      .from('user_profiles')
      .select('full_name, specialty, role')
      .eq('id', user.id)
      .maybeSingle()
      .then(({ data }) => {
        setFullName(data?.full_name ?? '')
        setSpecialtySlug(toSpecialtySlug(data?.specialty ?? null))
        setGrade(data?.role ?? null)
        setLoading(false)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user])

  const handleSave = async () => {
    if (!user) return
    setSaving(true)
    const { error } = await supabase
      .from('user_profiles')
      .update({ full_name: fullName.trim() || null, specialty: specialtySlug, role: grade })
      .eq('id', user.id)
    setSaving(false)
    if (error) {
      toast.error('Could not save your profile', { description: error.message })
      return
    }
    toast.success('Profile updated')
  }

  const handleSignOut = async () => {
    await signOut()
    router.push('/')
  }

  if (loading) {
    return (
      <AccountContainer className="flex items-center justify-center">
        <Loader2 className="size-6 animate-spin text-fg-subtle" />
      </AccountContainer>
    )
  }

  return (
    <AccountContainer className="max-w-[640px]">
      <AccountPageHeader title="Settings" subtitle="Your profile, appearance and notifications." />

      <div className="space-y-8">
        <AccountSection title="Profile">
          <div className="space-y-4 rounded-lg border border-border bg-surface p-5">
            <Field label="Name">
              <Input value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Dr Jai Rajput" />
            </Field>
            <Field label="Specialty">
              <SpecialtyCombobox value={specialtySlug} onChange={setSpecialtySlug} />
            </Field>
            <Field label="Grade">
              <GradeSelect value={grade} onChange={setGrade} />
            </Field>
            <div className="flex justify-end pt-1">
              <Button onClick={handleSave} disabled={saving}>
                {saving ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
                {saving ? 'Saving…' : 'Save changes'}
              </Button>
            </div>
          </div>
        </AccountSection>

        <AccountSection title="Appearance">
          <div className="flex items-center justify-between rounded-lg border border-border bg-surface p-5">
            <div>
              <p className="text-[0.9375rem] font-medium text-fg">Theme</p>
              <p className="type-small text-fg-muted">Light or dark — follows your choice, not your system setting.</p>
            </div>
            <ThemeToggle />
          </div>
        </AccountSection>

        <AccountSection title="Notifications">
          <div className="rounded-lg border border-border bg-surface p-5">
            <p className="type-small text-fg-muted">
              In-app notifications for saved-event reminders and specialty alerts are on by default — see the bell icon. Email digests
              are coming soon.
            </p>
          </div>
        </AccountSection>

        <Separator />

        <AccountSection title="Account">
          <Button variant="outline" onClick={handleSignOut} className="w-full sm:w-auto">
            <LogOut className="size-4" />
            Sign out
          </Button>
        </AccountSection>
      </div>
    </AccountContainer>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="type-mono-label text-fg-subtle">{label}</label>
      {children}
    </div>
  )
}
