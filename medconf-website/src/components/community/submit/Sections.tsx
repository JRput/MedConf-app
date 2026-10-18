'use client'

import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { SpecialtyCombobox } from '@/components/account/SpecialtyCombobox'
import { UK_NATIONS, LIMITS } from '@/lib/community/schema'
import { cn } from '@/lib/utils'
import { Field, describedBy } from '../Field'
import { COMMON_COUNTRIES, OTHER_COUNTRY, UK, specialtyLabel, type SubmitValues } from './logic'
import { DuplicateCheck } from './DuplicateCheck'

export interface Ctx {
  v: SubmitValues
  set: <K extends keyof SubmitValues>(k: K, val: SubmitValues[K]) => void
  /** Error for a payload key, only once touched or after a failed submit. */
  err: (key: string) => string | undefined
  touch: (key: string) => void
  today: string
}

const control = 'h-11'
const textarea =
  'w-full min-w-0 rounded-md border border-border bg-surface px-3 py-2.5 text-base md:text-sm text-fg shadow-xs placeholder:text-fg-subtle outline-none transition-[border-color,box-shadow] duration-150 focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-ring/35 aria-invalid:border-danger'
const checkLabel = 'flex min-h-11 cursor-pointer items-center gap-2.5 type-small text-fg'
const checkbox = 'size-4 shrink-0 cursor-pointer accent-brand'

function TextField({
  ctx,
  k,
  id,
  label,
  optional,
  hint,
  type,
  placeholder,
  inputMode,
  maxLength,
  min,
  autoComplete,
  className,
}: {
  ctx: Ctx
  k: keyof SubmitValues & string
  id: string
  label: string
  optional?: boolean
  hint?: string
  type?: string
  placeholder?: string
  inputMode?: 'url' | 'decimal' | 'text'
  maxLength?: number
  min?: string
  autoComplete?: string
  className?: string
}) {
  const e = ctx.err(k === 'cpd_points' ? 'cpd_points' : k)
  return (
    <Field id={id} label={label} optional={optional} hint={hint} error={e} className={className}>
      <Input
        id={id}
        type={type}
        inputMode={inputMode}
        placeholder={placeholder}
        maxLength={maxLength}
        min={min}
        autoComplete={autoComplete}
        className={control}
        value={ctx.v[k] as string}
        onChange={(ev) => ctx.set(k, ev.target.value as never)}
        onBlur={() => ctx.touch(k)}
        aria-invalid={!!e}
        aria-describedby={describedBy(id, e, hint)}
      />
    </Field>
  )
}

function SelectField({
  ctx,
  id,
  label,
  errKey,
  value,
  onChange,
  placeholder,
  children,
  hint,
}: {
  ctx: Ctx
  id: string
  label: string
  errKey: string
  value: string
  onChange: (v: string) => void
  placeholder: string
  children: React.ReactNode
  hint?: string
}) {
  const e = ctx.err(errKey)
  return (
    <Field id={id} label={label} error={e} hint={hint}>
      <Select
        value={value}
        onValueChange={(nv) => {
          onChange(nv)
          ctx.touch(errKey)
        }}
        onOpenChange={(o) => {
          if (!o) ctx.touch(errKey)
        }}
      >
        <SelectTrigger id={id} className={cn(control, 'w-full')} aria-invalid={!!e} aria-describedby={describedBy(id, e, hint)}>
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent position="popper">{children}</SelectContent>
      </Select>
    </Field>
  )
}

export function BasicsSection({ ctx }: { ctx: Ctx }) {
  const { v, set } = ctx
  return (
    <>
      <TextField ctx={ctx} k="conference_name" id="sub-name" label="Event name" maxLength={LIMITS.name} autoComplete="off" />
      <TextField
        ctx={ctx}
        k="organiser_url"
        id="sub-url"
        label="Organiser link"
        type="url"
        inputMode="url"
        placeholder="https://"
        hint="The organiser's own page for this event. We check it for details you leave out."
        autoComplete="off"
      />
      <DuplicateCheck name={v.conference_name} organiserUrl={v.organiser_url} />
      <div className="grid gap-3 sm:grid-cols-2">
        <SelectField ctx={ctx} id="sub-type" label="Event type" errKey="event_type" value={v.event_type} onChange={(x) => set('event_type', x as SubmitValues['event_type'])} placeholder="Choose a type">
          <SelectItem value="conference">Conference</SelectItem>
          <SelectItem value="workshop">Workshop</SelectItem>
          <SelectItem value="course">Course</SelectItem>
        </SelectField>
        <SelectField ctx={ctx} id="sub-format" label="Format" errKey="event_format" value={v.event_format} onChange={(x) => set('event_format', x as SubmitValues['event_format'])} placeholder="Choose a format">
          <SelectItem value="in_person">In person</SelectItem>
          <SelectItem value="online">Online</SelectItem>
          <SelectItem value="hybrid">Hybrid</SelectItem>
        </SelectField>
      </div>
      <label className={checkLabel}>
        <input type="checkbox" className={checkbox} checked={v.is_flagship} onChange={(e) => set('is_flagship', e.target.checked)} />
        This is a flagship annual congress
      </label>
    </>
  )
}

export function WhenSection({ ctx }: { ctx: Ctx }) {
  const { v, today } = ctx
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <TextField ctx={ctx} k="start_date" id="sub-start" label="Start date" type="date" min={today} />
      <TextField ctx={ctx} k="end_date" id="sub-end" label="End date" optional type="date" min={v.start_date || today} />
      <TextField ctx={ctx} k="start_time" id="sub-time" label="Start time" optional type="time" />
    </div>
  )
}

export function WhereSection({ ctx }: { ctx: Ctx }) {
  const { v, set } = ctx
  const online = v.event_format === 'online'
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2">
        <SelectField ctx={ctx} id="sub-country" label="Country" errKey="country" value={v.country} onChange={(x) => set('country', x)} placeholder="Choose a country" hint={online ? 'For an online event, use the organiser’s country.' : undefined}>
          {COMMON_COUNTRIES.map((c) => (
            <SelectItem key={c} value={c}>
              {c}
            </SelectItem>
          ))}
          <SelectItem value={OTHER_COUNTRY}>Other country…</SelectItem>
        </SelectField>
        {v.country === OTHER_COUNTRY && (
          <TextField ctx={ctx} k="country_other" id="sub-country-other" label="Country name" maxLength={100} autoComplete="off" />
        )}
        {v.country === UK && (
          <Field id="sub-nation" label="Nation" optional>
            <Select value={v.uk_nation} onValueChange={(x) => set('uk_nation', x)}>
              <SelectTrigger id="sub-nation" className={cn(control, 'w-full')}>
                <SelectValue placeholder="Choose a nation" />
              </SelectTrigger>
              <SelectContent position="popper">
                {UK_NATIONS.map((n) => (
                  <SelectItem key={n} value={n}>
                    {n}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        )}
      </div>
      {!online && (
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField ctx={ctx} k="city" id="sub-city" label="City" optional maxLength={100} autoComplete="off" />
          <TextField ctx={ctx} k="venue_name" id="sub-venue" label="Venue" optional maxLength={LIMITS.short} autoComplete="off" />
        </div>
      )}
    </>
  )
}

export function SpecialtySection({ ctx }: { ctx: Ctx }) {
  const { v, set } = ctx
  const e = ctx.err('specialty')
  return (
    <div className="space-y-1.5" role="group" aria-labelledby="sub-specialty-label">
      <p id="sub-specialty-label" className="type-caption font-medium text-fg-muted">
        Closest specialty
      </p>
      <div
        className={cn('[&_button]:h-11', e && '[&_button]:border-danger')}
        onBlur={(ev) => {
          if (!ev.currentTarget.contains(ev.relatedTarget as Node | null)) ctx.touch('specialty')
        }}
      >
        <SpecialtyCombobox value={v.specialty_slug || null} onChange={(slug) => { set('specialty_slug', slug); ctx.touch('specialty') }} />
      </div>
      {v.specialty_slug && <p className="type-caption text-fg-subtle">Listed under {specialtyLabel(v.specialty_slug)}.</p>}
      {e && (
        <p role="alert" className="type-caption text-danger-text">
          {e}
        </p>
      )}
    </div>
  )
}

export function AbstractsCpdSection({ ctx }: { ctx: Ctx }) {
  const { v, set } = ctx
  return (
    <>
      <div className="space-y-1">
        <label className={checkLabel}>
          <input type="checkbox" className={checkbox} checked={v.cpd_accredited} onChange={(e) => set('cpd_accredited', e.target.checked)} />
          CPD accredited
        </label>
        {v.cpd_accredited && (
          <TextField ctx={ctx} k="cpd_points" id="sub-cpd" label="CPD points" optional inputMode="decimal" className="max-w-48" />
        )}
      </div>
      <div className="space-y-1">
        <label className={checkLabel}>
          <input type="checkbox" className={checkbox} checked={v.abstract_open} onChange={(e) => set('abstract_open', e.target.checked)} />
          Abstracts are open for submission
        </label>
        {v.abstract_open && (
          <div className="grid gap-3 sm:grid-cols-2">
            <TextField ctx={ctx} k="abstract_deadline" id="sub-abs" label="Abstract deadline" optional type="date" min={ctx.today} />
            <TextField ctx={ctx} k="abstract_deadline_note" id="sub-abs-note" label="Deadline note" optional maxLength={LIMITS.short} hint="For example, late-breaking abstracts close later." />
          </div>
        )}
      </div>
    </>
  )
}

export function DescriptionSection({ ctx }: { ctx: Ctx }) {
  const { v, set } = ctx
  const e = ctx.err('description')
  const n = v.description.length
  return (
    <Field id="sub-desc" label="Brief description" optional error={e}>
      <textarea
        id="sub-desc"
        rows={5}
        className={textarea}
        value={v.description}
        onChange={(ev) => set('description', ev.target.value)}
        onBlur={() => ctx.touch('description')}
        aria-invalid={!!e}
        aria-describedby={e ? 'sub-desc-error' : 'sub-desc-count'}
      />
      <p id="sub-desc-count" className={cn('text-right type-caption', n > LIMITS.description ? 'text-danger-text' : 'text-fg-subtle')}>
        {n.toLocaleString('en-GB')} / {LIMITS.description.toLocaleString('en-GB')}
      </p>
    </Field>
  )
}

export function LinksSection({ ctx }: { ctx: Ctx }) {
  const { v, set } = ctx
  const e = ctx.err('note')
  return (
    <>
      <TextField ctx={ctx} k="booking_url" id="sub-booking" label="Booking link" optional type="url" inputMode="url" placeholder="https://" autoComplete="off" />
      <TextField
        ctx={ctx}
        k="evidence_url"
        id="sub-evidence"
        label="Evidence link"
        optional
        type="url"
        inputMode="url"
        placeholder="https://"
        hint="A page that confirms these details, if it differs from the organiser link."
        autoComplete="off"
      />
      <Field id="sub-note" label="Note for the moderator" optional error={e}>
        <textarea
          id="sub-note"
          rows={3}
          maxLength={LIMITS.note}
          className={textarea}
          value={v.note}
          onChange={(ev) => set('note', ev.target.value)}
          onBlur={() => ctx.touch('note')}
          aria-invalid={!!e}
          aria-describedby={e ? 'sub-note-error' : undefined}
        />
      </Field>
    </>
  )
}
