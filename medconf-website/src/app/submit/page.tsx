import type { Metadata } from 'next'
import { Suspense } from 'react'
import { SubmitEventForm } from '@/components/community/submit/SubmitEventForm'

export const metadata: Metadata = {
  title: 'Submit an event — MedConf',
  description: 'Know a medical conference, course or workshop that is not listed? Submit it for review.',
}

export default function SubmitPage() {
  return (
    <Suspense fallback={null}>
      <SubmitEventForm />
    </Suspense>
  )
}
