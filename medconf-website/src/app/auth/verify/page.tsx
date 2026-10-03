// src/app/auth/verify/page.tsx
import Link from 'next/link'
import { Mail } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { AuthCard } from '@/components/auth/AuthCard'

// Still a plain server component — it has no state, it just tells you what
// happens next. The pulsing gradient envelope tile is gone; the icon is a
// flat tile, and the spam-folder tip is a quiet note rather than a callout
// panel inside a panel.
export default function VerifyPage() {
  return (
    <AuthCard
      title="Check your email"
      intro="We've sent a verification link to the address you signed up with. Open it to activate your account — then you'll set your specialty and grade once, and land on your dashboard."
      footer={
        <Link href="/auth/login" className="font-medium text-brand-text hover:underline">
          Back to sign in
        </Link>
      }
    >
      <div className="flex items-start gap-3 rounded-md border border-border bg-surface-muted px-3 py-3">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-surface">
          <Mail className="size-4 text-fg-muted" aria-hidden />
        </span>
        <p className="text-[0.8125rem] leading-relaxed text-fg-muted">
          Nothing after a few minutes? Check your spam or quarantine folder — NHS mail filters are strict. The link
          expires after 24 hours; sign in again to send a fresh one.
        </p>
      </div>

      <Button variant="outline" className="mt-4 w-full" asChild>
        <Link href="/conferences">Browse the directory meanwhile</Link>
      </Button>
    </AuthCard>
  )
}
