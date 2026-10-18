'use client'

import { useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { toast } from 'sonner'
import {
  AlertCircle,
  Award,
  Banknote,
  CalendarDays,
  Check,
  FileText,
  Link2,
  Loader2,
  MapPin,
  MessageSquareText,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useAuth } from '@/hooks/useAuth'
import { useSubmitContribution, friendlySubmitError } from '@/hooks/useCommunity'
import { createSupabaseClient } from '@/lib/supabase'
import { feesPayloadToDraft } from '@/lib/community/moderation'
import {
  buildAddInfoRaw,
  buildResubmitPatch,
  resolveSections,
  valuesFromPayload,
  type AddInfoValues,
} from '@/lib/community/add-info-form'
import { emptySections } from '@/lib/community/overlay'
import { makeAddInfoSchema, todayUtc } from '@/lib/community/schema'
import { emptyFeesDraft, isFeesDraftEmpty, validateFeesDraft, type FeesDraft } from '@/lib/community/fees-draft'
import type { AddInfoPayload, AddInfoSection } from '@/lib/community/types'
import type { Conference, PricingTier } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Field, describedBy } from './Field'
import { FeeQuickEditor } from './FeeQuickEditor'
import { PRESS } from './press'

const SECTION_META: Record<AddInfoSection, { label: string; Icon: typeof CalendarDays }> = {
  dates: { label: 'Dates', Icon: CalendarDays },
  venue: { label: 'Venue & format', Icon: MapPin },
  fees: { label: 'Fees', Icon: Banknote },
  abstracts: { label: 'Abstracts', Icon: FileText },
  cpd: { label: 'CPD', Icon: Award },
  links: { label: 'Links', Icon: Link2 },
  note: { label: 'Note', Icon: MessageSquareText },
}

const control = 'h-11'
const textarea =
  'w-full min-w-0 rounded-md border border-border bg-surface px-3 py-2.5 text-base md:text-sm text-fg shadow-xs placeholder:text-fg-subtle outline-none transition-[border-color,box-shadow] duration-150 focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-ring/35 aria-invalid:border-danger'

type Values = AddInfoValues

export interface AddInfoDialogProps {
  /** The listing, ideally the community-overlaid one so already-filled fields are not re-offered. */
  conference: Conference
  /** Tiers currently displayed for the listing (scraped or community). */
  tiers: PricingTier[]
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Pre-expands one section (used by the inline "Know the fees? Add them" prompts). */
  initialSection?: AddInfoSection
  /** Resubmit mode: prefill from an earlier payload (a `needs_info` contribution). */
  initialPayload?: AddInfoPayload
  /** Resubmit mode: UPDATE this contribution (payload, note, evidence, status='pending') instead of inserting. */
  contributionId?: string
}

export function AddInfoDialog({ conference, tiers, open, onOpenChange, initialSection, initialPayload, contributionId }: AddInfoDialogProps) {
  const { user, loading } = useAuth()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        // Centre-origin modal: 200 ms ease-out in from scale .95 / opacity 0, 150 ms out.
        // Reduced motion keeps the opacity fade but drops the scale.
        className={cn(
          'max-h-[90dvh] gap-5 overflow-y-auto bg-surface p-5 sm:max-w-xl sm:p-6',
          'data-[state=open]:[animation-timing-function:cubic-bezier(0.23,1,0.32,1)] data-[state=open]:duration-200 data-[state=closed]:duration-150',
          'motion-reduce:data-[state=open]:zoom-in-100 motion-reduce:data-[state=closed]:zoom-out-100'
        )}
      >
        <DialogHeader>
          <DialogTitle className="type-h3 text-fg-strong">Add missing info</DialogTitle>
          <DialogDescription className="type-small text-fg-muted">
            {conference.conference_name}. A moderator reviews everything before it appears, and organiser data always takes priority.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <p className="type-small text-fg-subtle">Checking your session…</p>
        ) : !user ? (
          <SignInPrompt />
        ) : (
          <AddInfoForm
            conference={conference}
            tiers={tiers}
            initialSection={initialSection}
            initialPayload={initialPayload}
            contributionId={contributionId}
            onDone={() => onOpenChange(false)}
            onCancel={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function SignInPrompt() {
  return (
    <div className="space-y-4 rounded-lg border border-border bg-surface-muted p-4">
      <p className="type-body text-fg">Sign in to add information to this event. It only takes a moment.</p>
      <div className="flex flex-wrap gap-2">
        <Button asChild size="lg" className={PRESS}>
          <Link href="/auth/login">Sign in</Link>
        </Button>
        <Button asChild size="lg" variant="outline" className={PRESS}>
          <Link href="/auth/signup">Create an account</Link>
        </Button>
      </div>
    </div>
  )
}

function AddInfoForm({
  conference,
  tiers,
  initialSection,
  initialPayload,
  contributionId,
  onDone,
  onCancel,
}: {
  conference: Conference
  tiers: PricingTier[]
  initialSection?: AddInfoSection
  initialPayload?: AddInfoPayload
  contributionId?: string
  onDone: () => void
  onCancel: () => void
}) {
  // On resubmit, keep every section the member already filled even if the listing has since gained that
  // field, otherwise their answers silently vanish from the form.
  const resolved = useMemo(
    () => resolveSections(emptySections(conference, tiers), initialPayload, initialSection),
    [conference, tiers, initialPayload, initialSection]
  )
  const sections = resolved.offered
  const { submit, submitting } = useSubmitContribution()
  const [values, setValues] = useState<Values>(() => valuesFromPayload(initialPayload))
  const [fees, setFees] = useState<FeesDraft>(() =>
    initialPayload?.fees ? feesPayloadToDraft(initialPayload.fees) : emptyFeesDraft(tiers.find((t) => t.currency)?.currency ?? 'GBP')
  )
  const [openSections, setOpenSections] = useState<Set<AddInfoSection>>(() => new Set(resolved.active))
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const [attempted, setAttempted] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const formRef = useRef<HTMLFormElement>(null)

  const set = <K extends keyof Values>(k: K, v: Values[K]) => setValues((p) => ({ ...p, [k]: v }))
  const touch = (key: string) => setTouched((p) => (p.has(key) ? p : new Set(p).add(key)))
  const isOpen = (s: AddInfoSection) => openSections.has(s)
  const toggle = (s: AddInfoSection) =>
    setOpenSections((p) => {
      const n = new Set(p)
      if (n.has(s)) n.delete(s)
      else n.add(s)
      return n
    })

  // Build the raw payload from whatever sections are open and filled.
  const raw = useMemo(
    () => buildAddInfoRaw(values, fees, openSections, !!conference.description),
    [values, fees, openSections, conference.description]
  )

  const schema = useMemo(
    () => makeAddInfoSchema({ startDate: conference.start_date, endDate: conference.end_date }),
    [conference.start_date, conference.end_date]
  )
  const parsed = useMemo(() => schema.safeParse(raw), [schema, raw])

  // Issue path -> message, first issue per path. Fees are validated by the editor itself.
  const { fieldErrors, formError, feesInvalid } = useMemo(() => {
    const fe: Record<string, string> = {}
    let form: string | null = null
    let feesBad = false
    if (!parsed.success) {
      for (const issue of parsed.error.issues) {
        if (issue.path[0] === 'fees') {
          feesBad = true
          continue
        }
        if (issue.path.length === 0) {
          form = form ?? issue.message
          continue
        }
        const key = issue.path.join('.')
        if (!fe[key]) fe[key] = issue.message
      }
    }
    return { fieldErrors: fe, formError: form, feesInvalid: feesBad }
  }, [parsed])

  const err = (key: string) => (attempted || touched.has(key) ? fieldErrors[key] : undefined)
  const sectionHasContent = (s: AddInfoSection): boolean => {
    const f = (raw.fields ?? {}) as Record<string, unknown>
    switch (s) {
      case 'dates': return !!(f.start_date || f.end_date || f.start_time)
      case 'venue': return !!(f.event_format || f.venue_name || f.city || f.region)
      case 'fees': return !!raw.fees
      case 'abstracts': return !!(f.abstract_deadline || f.abstract_deadline_note)
      case 'cpd': return !!(f.cpd_accredited || f.cpd_points !== undefined)
      case 'links': return !!(f.organiser_url || f.booking_url)
      case 'note': return !!(f.note || f.description)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setAttempted(true)
    setServerError(null)
    const feesBlocked = openSections.has('fees') && !isFeesDraftEmpty(fees) && !validateFeesDraft(fees).payload
    if (!parsed.success || feesBlocked) {
      // Never fail silently: the offending field may be scrolled out of view inside the dialog.
      requestAnimationFrame(() =>
        formRef.current?.querySelector('[aria-invalid="true"], [role="alert"]')?.scrollIntoView({ block: 'center', behavior: 'smooth' })
      )
      return
    }

    const data = parsed.data
    if (contributionId) {
      // Resubmit after "needs info": RLS only lets the owner flip needs_info -> pending.
      setSaving(true)
      try {
        const { data: updated, error: updError } = await createSupabaseClient()
          .from('community_contributions')
          .update(buildResubmitPatch(data))
          .eq('id', contributionId)
          .select('id, status')
        if (updError) {
          setServerError(friendlySubmitError(updError))
        } else if (!updated || updated.length === 0) {
          setServerError('This contribution can no longer be edited. Refresh the page to see its current status.')
        } else if ((updated[0] as { status?: string }).status !== 'pending') {
          setServerError('The resubmit was not applied. Please try again.')
        } else {
          toast.success('Resubmitted. A moderator will review it again.')
          onDone()
        }
      } catch (e) {
        setServerError(friendlySubmitError({ message: e instanceof Error ? e.message : String(e) }))
      } finally {
        setSaving(false)
      }
      return
    }
    const res = await submit({
      kind: 'add_info',
      conference_id: conference.id,
      payload: data as AddInfoPayload,
      note: data.note ?? null,
      evidence_url: data.evidence_url ?? null,
    })
    if (res.ok) {
      toast.success('Thanks — a moderator will review this.')
      onDone()
    } else {
      setServerError(res.message)
    }
  }

  const showFeesErrors = attempted && (feesInvalid || (openSections.has('fees') && !validateFeesDraft(fees).payload && !isFeesDraftEmpty(fees)))
  const today = todayUtc()

  return (
    <form ref={formRef} onSubmit={handleSubmit} noValidate className="space-y-5">
      <div>
        <p className="mb-2 type-caption font-medium text-fg-muted" id="addinfo-chips-label">
          What can you add? Only missing details are listed.
        </p>
        <div role="group" aria-labelledby="addinfo-chips-label" className="flex flex-wrap gap-2">
          {sections.map((s) => {
            const { label, Icon } = SECTION_META[s]
            const active = isOpen(s)
            const filled = sectionHasContent(s)
            return (
              <button
                key={s}
                type="button"
                onClick={() => toggle(s)}
                aria-expanded={active}
                aria-controls={`addinfo-${s}`}
                className={cn(
                  PRESS,
                  'inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-md border px-3.5 type-small font-medium',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-bg',
                  active
                    ? 'border-brand-border bg-brand-subtle text-brand-text'
                    : 'border-border bg-surface text-fg-muted [@media(hover:hover)_and_(pointer:fine)]:hover:border-border-strong [@media(hover:hover)_and_(pointer:fine)]:hover:text-fg'
                )}
              >
                {filled ? <Check className="size-4" aria-hidden /> : <Icon className="size-4" strokeWidth={1.75} aria-hidden />}
                {label}
              </button>
            )
          })}
        </div>
      </div>

      {openSections.size === 0 && (
        <p className="rounded-lg border border-dashed border-border px-4 py-5 text-center type-small text-fg-muted">
          Pick a section above to start.
        </p>
      )}

      {isOpen('dates') && (
        <SubForm id="addinfo-dates" title="Dates">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="ai-start" label="Start date" error={err('fields.start_date')}>
              <Input id="ai-start" type="date" min={today} className={control} value={values.start_date}
                onChange={(e) => set('start_date', e.target.value)} onBlur={() => touch('fields.start_date')}
                aria-invalid={!!err('fields.start_date')} aria-describedby={describedBy('ai-start', err('fields.start_date'))} />
            </Field>
            <Field id="ai-end" label="End date" optional error={err('fields.end_date')}>
              <Input id="ai-end" type="date" min={values.start_date || today} className={control} value={values.end_date}
                onChange={(e) => set('end_date', e.target.value)} onBlur={() => touch('fields.end_date')}
                aria-invalid={!!err('fields.end_date')} aria-describedby={describedBy('ai-end', err('fields.end_date'))} />
            </Field>
            <Field id="ai-time" label="Start time" optional error={err('fields.start_time')}>
              <Input id="ai-time" type="time" className={control} value={values.start_time}
                onChange={(e) => set('start_time', e.target.value)} onBlur={() => touch('fields.start_time')}
                aria-invalid={!!err('fields.start_time')} aria-describedby={describedBy('ai-time', err('fields.start_time'))} />
            </Field>
          </div>
        </SubForm>
      )}

      {isOpen('venue') && (
        <SubForm id="addinfo-venue" title="Venue & format">
          <Field id="ai-format" label="Format">
            <Select value={values.event_format} onValueChange={(v) => set('event_format', v as Values['event_format'])}>
              <SelectTrigger id="ai-format" className={cn(control, 'w-full')}>
                <SelectValue placeholder="Choose a format" />
              </SelectTrigger>
              <SelectContent position="popper">
                <SelectItem value="in_person">In person</SelectItem>
                <SelectItem value="online">Online</SelectItem>
                <SelectItem value="hybrid">Hybrid</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          {values.event_format !== 'online' && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field id="ai-venue" label="Venue" optional error={err('fields.venue_name')} className="sm:col-span-2">
                <Input id="ai-venue" className={control} maxLength={200} value={values.venue_name}
                  onChange={(e) => set('venue_name', e.target.value)} onBlur={() => touch('fields.venue_name')}
                  aria-invalid={!!err('fields.venue_name')} aria-describedby={describedBy('ai-venue', err('fields.venue_name'))} />
              </Field>
              <Field id="ai-city" label="City" optional error={err('fields.city')}>
                <Input id="ai-city" className={control} maxLength={100} value={values.city}
                  onChange={(e) => set('city', e.target.value)} onBlur={() => touch('fields.city')}
                  aria-invalid={!!err('fields.city')} aria-describedby={describedBy('ai-city', err('fields.city'))} />
              </Field>
              <Field id="ai-region" label="Region or country" optional error={err('fields.region')}>
                <Input id="ai-region" className={control} maxLength={100} value={values.region}
                  onChange={(e) => set('region', e.target.value)} onBlur={() => touch('fields.region')}
                  aria-invalid={!!err('fields.region')} aria-describedby={describedBy('ai-region', err('fields.region'))} />
              </Field>
            </div>
          )}
        </SubForm>
      )}

      {isOpen('fees') && (
        <SubForm id="addinfo-fees" title="Fees">
          <FeeQuickEditor value={fees} onChange={setFees} showAllErrors={showFeesErrors} idPrefix="ai-fees" />
        </SubForm>
      )}

      {isOpen('abstracts') && (
        <SubForm id="addinfo-abstracts" title="Abstracts">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="ai-abs-deadline" label="Abstract deadline" optional error={err('fields.abstract_deadline')}>
              <Input id="ai-abs-deadline" type="date" min={today} max={conference.start_date ?? undefined} className={control}
                value={values.abstract_deadline} onChange={(e) => set('abstract_deadline', e.target.value)}
                onBlur={() => touch('fields.abstract_deadline')} aria-invalid={!!err('fields.abstract_deadline')}
                aria-describedby={describedBy('ai-abs-deadline', err('fields.abstract_deadline'))} />
            </Field>
            <Field id="ai-abs-note" label="Or a short note" optional hint="e.g. Opens in January" error={err('fields.abstract_deadline_note')}>
              <Input id="ai-abs-note" className={control} maxLength={200} value={values.abstract_deadline_note}
                onChange={(e) => set('abstract_deadline_note', e.target.value)} onBlur={() => touch('fields.abstract_deadline_note')}
                aria-invalid={!!err('fields.abstract_deadline_note')}
                aria-describedby={describedBy('ai-abs-note', err('fields.abstract_deadline_note'), 'x')} />
            </Field>
          </div>
          <label className="flex min-h-11 cursor-pointer items-center gap-2 type-small text-fg">
            <input type="checkbox" className="size-4 cursor-pointer accent-brand" checked={values.abstract_open}
              onChange={(e) => set('abstract_open', e.target.checked)} />
            Submissions are currently open
          </label>
        </SubForm>
      )}

      {isOpen('cpd') && (
        <SubForm id="addinfo-cpd" title="CPD">
          <label className="flex min-h-11 cursor-pointer items-center gap-2 type-small text-fg">
            <input type="checkbox" className="size-4 cursor-pointer accent-brand"
              checked={values.cpd_accredited || values.cpd_points.trim() !== ''}
              disabled={values.cpd_points.trim() !== ''}
              onChange={(e) => set('cpd_accredited', e.target.checked)} />
            This event is CPD accredited
          </label>
          <Field id="ai-cpd-points" label="CPD points" optional error={err('fields.cpd_points')} className="sm:max-w-44">
            <Input id="ai-cpd-points" inputMode="decimal" className={control} value={values.cpd_points}
              onChange={(e) => set('cpd_points', e.target.value)} onBlur={() => touch('fields.cpd_points')}
              aria-invalid={!!err('fields.cpd_points')} aria-describedby={describedBy('ai-cpd-points', err('fields.cpd_points'))} />
          </Field>
        </SubForm>
      )}

      {isOpen('links') && (
        <SubForm id="addinfo-links" title="Links">
          <Field id="ai-org" label="Organiser page" optional error={err('fields.organiser_url')}>
            <Input id="ai-org" type="url" inputMode="url" placeholder="https://" className={control} value={values.organiser_url}
              onChange={(e) => set('organiser_url', e.target.value)} onBlur={() => touch('fields.organiser_url')}
              aria-invalid={!!err('fields.organiser_url')} aria-describedby={describedBy('ai-org', err('fields.organiser_url'))} />
          </Field>
          <Field id="ai-book" label="Booking page" optional error={err('fields.booking_url')}>
            <Input id="ai-book" type="url" inputMode="url" placeholder="https://" className={control} value={values.booking_url}
              onChange={(e) => set('booking_url', e.target.value)} onBlur={() => touch('fields.booking_url')}
              aria-invalid={!!err('fields.booking_url')} aria-describedby={describedBy('ai-book', err('fields.booking_url'))} />
          </Field>
        </SubForm>
      )}

      {isOpen('note') && (
        <SubForm id="addinfo-note" title="Note">
          {!conference.description && (
            <Field id="ai-desc" label="Short description" optional hint="Shown as a community description." error={err('fields.description')}>
              <textarea id="ai-desc" rows={3} maxLength={2000} className={textarea} value={values.description}
                onChange={(e) => set('description', e.target.value)} onBlur={() => touch('fields.description')}
                aria-invalid={!!err('fields.description')} aria-describedby={describedBy('ai-desc', err('fields.description'), 'x')} />
            </Field>
          )}
          <Field id="ai-note" label="Public note" optional hint="Shown on the event page as a community note." error={err('fields.note')}>
            <textarea id="ai-note" rows={3} maxLength={1000} className={textarea} value={values.note}
              onChange={(e) => set('note', e.target.value)} onBlur={() => touch('fields.note')}
              aria-invalid={!!err('fields.note')} aria-describedby={describedBy('ai-note', err('fields.note'), 'x')} />
          </Field>
        </SubForm>
      )}

      {openSections.size > 0 && (
        <div className="space-y-3 border-t border-border-subtle pt-4">
          <Field id="ai-evidence" label="Where did you find this?" optional hint="A link a moderator can check." error={err('evidence_url')}>
            <Input id="ai-evidence" type="url" inputMode="url" placeholder="https://" className={control} value={values.evidence_url}
              onChange={(e) => set('evidence_url', e.target.value)} onBlur={() => touch('evidence_url')}
              aria-invalid={!!err('evidence_url')} aria-describedby={describedBy('ai-evidence', err('evidence_url'), 'x')} />
          </Field>
          <Field id="ai-mod-note" label="Message for the moderator" optional hint="Private. Not shown on the event page." error={err('note')}>
            <textarea id="ai-mod-note" rows={2} maxLength={1000} className={textarea} value={values.moderator_note}
              onChange={(e) => set('moderator_note', e.target.value)} onBlur={() => touch('note')}
              aria-invalid={!!err('note')} aria-describedby={describedBy('ai-mod-note', err('note'), 'x')} />
          </Field>
        </div>
      )}

      {attempted && formError && openSections.size > 0 && (
        <Alert>{formError}</Alert>
      )}
      {attempted && openSections.size === 0 && <Alert>Pick at least one section and fill it in before sending.</Alert>}
      {attempted && openSections.size > 0 && (!parsed.success || showFeesErrors) && (
        <Alert>
          Some details need fixing before this can be sent. Check the fields marked in red
          {!parsed.success && parsed.error.issues[0] ? ` (${parsed.error.issues[0].message})` : ''}.
        </Alert>
      )}
      {serverError && <Alert>{serverError}</Alert>}

      <DialogFooter className="gap-2 sm:items-center">
        <Button type="button" variant="ghost" size="lg" className={PRESS} onClick={onCancel} disabled={submitting || saving}>
          Cancel
        </Button>
        <Button type="submit" size="lg" className={PRESS} disabled={submitting || saving} aria-busy={submitting || saving}>
          {submitting || saving ? (
            <>
              <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />
              Sending…
            </>
          ) : (
            contributionId ? 'Resubmit for review' : 'Send for review'
          )}
        </Button>
      </DialogFooter>
    </form>
  )
}

function SubForm({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <fieldset
      id={id}
      className="min-w-0 space-y-3 rounded-lg border border-border-subtle bg-surface-muted p-4 animate-in fade-in-0 duration-150 motion-reduce:animate-none"
    >
      <legend className="px-1 type-mono-label text-fg-subtle">{title}</legend>
      {children}
    </fieldset>
  )
}

function Alert({ children }: { children: React.ReactNode }) {
  return (
    <div role="alert" className="flex items-start gap-2 rounded-md border border-danger-border bg-danger-subtle px-3 py-2.5 type-small text-danger-text">
      <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>{children}</span>
    </div>
  )
}
