import Link from 'next/link'
import { CheckCircle2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { PRESS } from '../press'

export function SubmitSuccess({ resubmitted, onAnother }: { resubmitted: boolean; onAnother: () => void }) {
  return (
    <div role="status" className="mx-auto max-w-xl rounded-lg border border-border bg-surface p-6 text-center sm:p-8">
      <CheckCircle2 className="mx-auto size-10 text-ok-text" strokeWidth={1.5} aria-hidden />
      <h2 className="mt-4 type-h2 text-fg-strong">{resubmitted ? 'Resubmitted. Thanks.' : 'Thanks, we have it'}</h2>
      <p className="mt-2 type-body text-fg-muted">
        {resubmitted
          ? 'Resubmitted — thanks. A moderator will take another look.'
          : 'Thanks — a moderator will review your submission. We also look up the organiser’s page to fill in anything missing.'}
      </p>
      <div className="mt-6 flex flex-col justify-center gap-2 sm:flex-row">
        <Button asChild size="lg" className={PRESS}>
          <Link href="/dashboard/contributions">View my contributions</Link>
        </Button>
        {!resubmitted && (
          <Button type="button" size="lg" variant="outline" className={PRESS} onClick={onAnother}>
            Submit another
          </Button>
        )}
      </div>
    </div>
  )
}
