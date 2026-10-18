import { MessageSquareText } from 'lucide-react'
import type { CommunityFact } from '@/lib/community/types'
import { CommunityTag } from './CommunityTag'

/**
 * Published free-text from members: 'note' facts, plus a 'description' fact
 * when the listing has no description of its own. Renders nothing otherwise.
 * Server-safe (no hooks); CommunityTag is the only client part.
 */
export function CommunityNotes({ facts, hasDescription }: { facts: CommunityFact[]; hasDescription: boolean }) {
  const published = facts.filter((f) => f.is_published && typeof f.value === 'string' && f.value.trim() !== '')
  const notes = published.filter((f) => f.field === 'note')
  const description = hasDescription ? null : published.filter((f) => f.field === 'description').at(-1) ?? null

  if (notes.length === 0 && !description) return null

  return (
    <section className="space-y-3" aria-labelledby="community-notes-heading">
      <h2 id="community-notes-heading" className="type-h3 flex items-center gap-2 text-fg-strong">
        <MessageSquareText className="size-4 text-fg-subtle" strokeWidth={1.75} aria-hidden />
        Community notes
      </h2>
      <ul className="space-y-2">
        {description && (
          <li className="space-y-1.5 rounded-lg border border-border bg-surface-muted px-4 py-3">
            <p className="flex items-center gap-2 type-caption font-medium text-fg-muted">
              About this event <CommunityTag />
            </p>
            <p className="type-body whitespace-pre-line text-fg-muted">{String(description.value)}</p>
          </li>
        )}
        {notes.map((n) => (
          <li key={n.id} className="rounded-lg border border-border bg-surface-muted px-4 py-3">
            <p className="type-body whitespace-pre-line text-fg-muted">{String(n.value)}</p>
          </li>
        ))}
      </ul>
      <p className="type-caption text-fg-subtle">Added by MedConf members · reviewed by moderators</p>
    </section>
  )
}
