'use client'

import { useMemo, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { CURRENCIES, FEE_LABELS, MAX_TIERS, todayUtc } from '@/lib/community/schema'
import { newTierDraft, validateFeesDraft, type FeesDraft, type TierDraft } from '@/lib/community/fees-draft'
import { currencySymbol } from '@/lib/conference-helpers'
import { Field, describedBy } from './Field'
import { PRESS } from './press'
import { cn } from '@/lib/utils'

const OTHER = '__other__'
const control = 'h-11'

/**
 * Simplified fee entry: currency, optional "from" price, and up to 12 tier
 * rows. Controlled — the parent owns the draft (see lib/community/fees-draft).
 * Errors show per field after blur, or all at once when `showAllErrors` is set
 * (the parent flips it after a failed submit).
 */
export function FeeQuickEditor({
  value,
  onChange,
  showAllErrors = false,
  idPrefix = 'fees',
}: {
  value: FeesDraft
  onChange: (next: FeesDraft) => void
  showAllErrors?: boolean
  idPrefix?: string
}) {
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const { errors: schemaErrors } = useMemo(() => validateFeesDraft(value), [value])

  const touch = (key: string) => setTouched((prev) => (prev.has(key) ? prev : new Set(prev).add(key)))
  const errorFor = (key: string): string | undefined => {
    if (!(showAllErrors || touched.has(key))) return undefined
    return schemaErrors[key] ?? blankPriceError(key)
  }
  // A touched-but-empty price is the commonest slip; zod never sees the row, so flag it here.
  const blankPriceError = (key: string) => {
    const m = /^tiers\.(\d+)\.price$/.exec(key)
    if (!m) return undefined
    const row = value.tiers[Number(m[1])]
    return row && row.price.trim() === '' ? 'Enter a price (0 if free)' : undefined
  }

  const setTier = (i: number, patch: Partial<TierDraft>) =>
    onChange({ ...value, tiers: value.tiers.map((t, j) => (j === i ? { ...t, ...patch } : t)) })

  const addTier = () => {
    if (value.tiers.length >= MAX_TIERS) return
    // Offer the first label not yet used so repeated "Add" does not stack duplicates.
    const used = new Set(value.tiers.map((t) => t.label))
    const next = FEE_LABELS.find((l) => !used.has(l)) ?? FEE_LABELS[0]
    onChange({ ...value, tiers: [...value.tiers, newTierDraft(next)] })
  }

  const removeTier = (i: number) => onChange({ ...value, tiers: value.tiers.filter((_, j) => j !== i) })
  const sym = currencySymbol(value.currency)

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field id={`${idPrefix}-currency`} label="Currency">
          <Select value={value.currency} onValueChange={(currency) => onChange({ ...value, currency })}>
            <SelectTrigger id={`${idPrefix}-currency`} className={cn(control, 'w-full')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent position="popper">
              {CURRENCIES.map((c) => (
                <SelectItem key={c} value={c}>
                  {c} ({currencySymbol(c).trim()})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field
          id={`${idPrefix}-from`}
          label="Fees start from"
          optional
          hint="Cheapest ticket, if you do not know each tier."
          error={errorFor('from_price')}
        >
          <div className="relative">
            <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center type-small text-fg-subtle">{sym}</span>
            <Input
              id={`${idPrefix}-from`}
              inputMode="decimal"
              className={cn(control, 'pl-8')}
              value={value.from_price}
              onChange={(e) => onChange({ ...value, from_price: e.target.value })}
              onBlur={() => touch('from_price')}
              aria-invalid={!!errorFor('from_price')}
              aria-describedby={describedBy(`${idPrefix}-from`, errorFor('from_price'), 'x')}
            />
          </div>
        </Field>
      </div>

      {value.tiers.length > 0 && (
        <ul className="space-y-3" aria-label="Fee tiers">
          {value.tiers.map((t, i) => {
            const rid = `${idPrefix}-t${i}`
            const labelErr = errorFor(`tiers.${i}.label`)
            const priceErr = errorFor(`tiers.${i}.price`)
            const dateErr = errorFor(`tiers.${i}.early_bird_deadline`)
            return (
              <li key={t.key} className="space-y-3 rounded-lg border border-border bg-surface p-3">
                <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_9rem_auto] sm:items-end">
                  <Field id={`${rid}-label`} label={`Tier ${i + 1}`} error={labelErr}>
                    {t.custom ? (
                      <Input
                        id={`${rid}-label`}
                        className={control}
                        placeholder="e.g. Nurse / AHP"
                        maxLength={40}
                        value={t.label}
                        onChange={(e) => setTier(i, { label: e.target.value })}
                        onBlur={() => touch(`tiers.${i}.label`)}
                        aria-invalid={!!labelErr}
                        aria-describedby={describedBy(`${rid}-label`, labelErr)}
                      />
                    ) : (
                      <Select
                        value={t.label}
                        onValueChange={(v) => {
                          if (v === OTHER) setTier(i, { custom: true, label: '' })
                          else setTier(i, { label: v, price: v === 'Free' && t.price.trim() === '' ? '0' : t.price })
                        }}
                      >
                        <SelectTrigger id={`${rid}-label`} className={cn(control, 'w-full')}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent position="popper">
                          {FEE_LABELS.map((l) => (
                            <SelectItem key={l} value={l}>
                              {l}
                            </SelectItem>
                          ))}
                          <SelectItem value={OTHER}>Other…</SelectItem>
                        </SelectContent>
                      </Select>
                    )}
                  </Field>
                  <Field id={`${rid}-price`} label="Price" error={priceErr}>
                    <div className="relative">
                      <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center type-small text-fg-subtle">{sym}</span>
                      <Input
                        id={`${rid}-price`}
                        inputMode="decimal"
                        className={cn(control, 'pl-8')}
                        value={t.price}
                        onChange={(e) => setTier(i, { price: e.target.value })}
                        onBlur={() => touch(`tiers.${i}.price`)}
                        aria-invalid={!!priceErr}
                        aria-describedby={describedBy(`${rid}-price`, priceErr)}
                      />
                    </div>
                  </Field>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-lg"
                    className={cn(PRESS, 'justify-self-end text-fg-subtle hover:text-danger-text')}
                    onClick={() => removeTier(i)}
                    aria-label={`Remove tier ${i + 1}`}
                  >
                    <Trash2 aria-hidden />
                  </Button>
                </div>

                <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                  <label className="flex min-h-11 cursor-pointer items-center gap-2 type-small text-fg">
                    <input
                      type="checkbox"
                      className="size-4 cursor-pointer accent-brand"
                      checked={t.is_early_bird}
                      onChange={(e) => setTier(i, { is_early_bird: e.target.checked })}
                    />
                    Early-bird price
                  </label>
                  {t.is_early_bird && (
                    <Field id={`${rid}-deadline`} label="Early-bird ends" optional error={dateErr} className="min-w-44">
                      <Input
                        id={`${rid}-deadline`}
                        type="date"
                        min={todayUtc()}
                        className={control}
                        value={t.early_bird_deadline}
                        onChange={(e) => setTier(i, { early_bird_deadline: e.target.value })}
                        onBlur={() => touch(`tiers.${i}.early_bird_deadline`)}
                        aria-invalid={!!dateErr}
                        aria-describedby={describedBy(`${rid}-deadline`, dateErr)}
                      />
                    </Field>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" variant="outline" className={cn(PRESS, 'h-11')} onClick={addTier} disabled={value.tiers.length >= MAX_TIERS}>
          <Plus aria-hidden />
          Add a fee tier
        </Button>
        <span className="type-caption text-fg-subtle">
          {value.tiers.length} of {MAX_TIERS}
        </span>
      </div>
      {errorFor('tiers') && (
        <p role="alert" className="type-caption text-danger-text">
          {errorFor('tiers')}
        </p>
      )}
    </div>
  )
}
