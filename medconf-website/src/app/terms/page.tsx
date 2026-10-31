import type { Metadata } from 'next'
import { loadLegal } from '@/lib/legal'
import { SITE_NAME } from '@/lib/site'
import { LegalPage } from '@/components/legal/LegalPage'

export const dynamic = 'force-static'

// Read the Markdown inside these functions, not at module scope, so `next dev`
// shows edits to legal/terms.md on the next page load. Production still builds
// the page once at deploy time (force-static).
export function generateMetadata(): Metadata {
  return {
    title: `${loadLegal('terms').title} — ${SITE_NAME}`,
    robots: { index: true, follow: true },
  }
}

export default function Page() {
  return <LegalPage doc={loadLegal('terms')} />
}
