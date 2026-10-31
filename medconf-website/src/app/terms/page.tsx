import type { Metadata } from 'next'
import { loadLegal } from '@/lib/legal'
import { SITE_NAME } from '@/lib/site'
import { LegalPage } from '@/components/legal/LegalPage'

export const dynamic = 'force-static'

const doc = loadLegal('terms')

export const metadata: Metadata = {
  title: `${doc.title} — ${SITE_NAME}`,
  robots: { index: true, follow: true },
}

export default function Page() {
  return <LegalPage doc={doc} />
}
