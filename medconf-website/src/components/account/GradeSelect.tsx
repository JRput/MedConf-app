'use client'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

/**
 * "Grade" is the UK clinical-training term for seniority — written to the
 * existing `user_profiles.role` column (unchanged name/shape, see
 * supabase_schema.sql:181) so the onboarding simplification (2 steps, not 3)
 * doesn't need a migration. Values match the original onboarding wizard's
 * ROLES list exactly, so no existing stored value falls outside this list.
 */
export const GRADES = [
  'Medical Student',
  'Foundation Doctor',
  'Core Trainee',
  'Registrar',
  'Fellow',
  'Consultant',
  'GP',
  'Nurse',
  'Allied Health',
  'Other',
] as const

export function GradeSelect({
  value,
  onChange,
  placeholder = 'Select your grade…',
}: {
  value: string | null
  onChange: (grade: string) => void
  placeholder?: string
}) {
  return (
    // Always pass a defined string (never `undefined`) so Radix's Select
    // stays controlled from first render — switching value from `undefined`
    // to a string after the first selection is what triggers React's
    // "changing from uncontrolled to controlled" warning.
    <Select value={value ?? ''} onValueChange={onChange}>
      <SelectTrigger className="w-full">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {GRADES.map((g) => (
          <SelectItem key={g} value={g}>
            {g}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
