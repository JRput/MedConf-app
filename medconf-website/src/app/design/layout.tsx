import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'MedConf — Design system',
  // Internal review surface. Never index it, never follow out of it.
  robots: { index: false, follow: false, nocache: true },
}

export default function DesignLayout({ children }: { children: React.ReactNode }) {
  // The new token system owns this route end to end — the legacy dark chrome is
  // suppressed for /design by SiteChrome in the root layout.
  return <div className="min-h-screen bg-bg font-sans text-fg">{children}</div>
}
