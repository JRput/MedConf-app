'use client'

import { useState } from 'react'
import { AccountContainer, AccountEmptyState, AccountPageHeader } from '@/components/account/AccountPageHeader'
import { QueueTable } from '@/components/moderation/QueueTable'
import { StatusTabs } from '@/components/moderation/StatusTabs'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useIsAdmin } from '@/hooks/useIsAdmin'
import { useModerationQueue } from '@/hooks/useModeration'
import { TAB_LABEL, type QueueTab } from '@/lib/community/moderation'

export default function ModerationQueuePage() {
  const isAdmin = useIsAdmin()

  if (isAdmin === null) {
    return (
      <AccountContainer>
        <Skeleton className="h-10 w-64" />
      </AccountContainer>
    )
  }
  if (!isAdmin) {
    return (
      <AccountContainer className="max-w-[640px]">
        <AccountEmptyState title="Admins only" description="This area is for MedConf moderators. If you should have access, ask the site owner to flag your account." />
      </AccountContainer>
    )
  }
  return <Queue />
}

function Queue() {
  const [tab, setTab] = useState<QueueTab>('pending')
  const { items, counts, loading, error, refresh } = useModerationQueue(tab)

  return (
    <AccountContainer>
      <AccountPageHeader
        title="Moderation"
        subtitle="Review community submissions before they appear on MedConf."
        action={
          <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
            Refresh
          </Button>
        }
      />
      <div className="space-y-4">
        <StatusTabs value={tab} counts={counts} onChange={setTab} />

        {error ? (
          <div role="alert" className="rounded-lg border border-danger-border bg-danger-subtle px-4 py-3 type-small text-danger-text">
            Could not load the queue: {error}
          </div>
        ) : loading && items.length === 0 ? (
          <div className="space-y-2" aria-busy>
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-11 w-full" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <AccountEmptyState
            title={tab === 'pending' ? 'Nothing waiting' : `No ${TAB_LABEL[tab].toLowerCase()} items`}
            description={tab === 'pending' ? 'New submissions will appear here, newest first.' : 'Items move here as they are reviewed.'}
          />
        ) : (
          <QueueTable items={items} />
        )}
      </div>
    </AccountContainer>
  )
}
