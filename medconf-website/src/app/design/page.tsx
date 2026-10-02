'use client'

import * as React from 'react'
import { Filter, Search, SlidersHorizontal, Check } from 'lucide-react'
import { toast } from 'sonner'

import { ThemeToggle } from '@/components/theme/ThemeToggle'
import { AccentToggle } from '@/components/theme/AccentToggle'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { Calendar } from '@/components/ui/calendar'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'

import { DateBlock } from '@/components/domain/DateBlock'
import { EventTypeBadge } from '@/components/domain/EventTypeBadge'
import { FormatBadge } from '@/components/domain/FormatBadge'
import { PriceLabel } from '@/components/domain/PriceLabel'
import { CpdLabel } from '@/components/domain/CpdLabel'
import { DeadlineBadge } from '@/components/domain/DeadlineBadge'
import { SocietyChip } from '@/components/domain/SocietyChip'
import { SaveToggle } from '@/components/domain/SaveToggle'
import { EventRow } from '@/components/domain/EventRow'
import { EventCardCompact } from '@/components/domain/EventCardCompact'

import { SAMPLE_EVENTS } from './sample-data'

export default function DesignPage() {
  const [saved, setSaved] = React.useState<Record<number, boolean>>({ 2: true })
  const [date, setDate] = React.useState<Date | undefined>(new Date())

  const toggleSave = (id: number) => setSaved((s) => ({ ...s, [id]: !s[id] }))

  return (
    <div className="mx-auto max-w-[1180px] px-4 pb-24 sm:px-6">
      <Header />

      {/* ------------------------------------------------------------ COLOUR */}
      <Section
        id="colour"
        title="Colour"
        note="One accent, used only for actions and links. Everything else is neutral; colour elsewhere always means something."
      >
        <SubHead>Warm neutral ramp</SubHead>
        <div className="grid grid-cols-6 gap-px overflow-hidden rounded-md border border-border sm:grid-cols-13">
          {['0', '25', '50', '100', '200', '300', '400', '500', '600', '700', '800', '900', '950'].map((step) => (
            <div key={step} className="flex flex-col">
              <div className="h-14" style={{ backgroundColor: `var(--n-${step})` }} />
              <div className="bg-surface px-1 py-1 text-center type-mono-label text-fg-subtle">{step}</div>
            </div>
          ))}
        </div>

        <SubHead className="mt-8">Surfaces, text and borders</SubHead>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <TokenTile name="bg" desc="page" swatch="var(--bg)" />
          <TokenTile name="surface" desc="cards, menus" swatch="var(--surface)" />
          <TokenTile name="surface-muted" desc="inset panels" swatch="var(--surface-muted)" />
          <TokenTile name="surface-sunken" desc="wells" swatch="var(--surface-sunken)" />
        </div>
        <div className="mt-3 grid gap-3 rounded-lg border border-border bg-surface p-4 sm:grid-cols-3">
          <p className="text-fg">
            <span className="type-mono-label block text-fg-subtle">fg</span>
            Primary body copy at 15px.
          </p>
          <p className="text-fg-muted">
            <span className="type-mono-label block text-fg-subtle">fg-muted</span>
            Secondary — meta lines, labels.
          </p>
          <p className="text-fg-subtle">
            <span className="type-mono-label block text-fg-subtle">fg-subtle</span>
            Tertiary — placeholders, dots.
          </p>
        </div>

        <SubHead className="mt-8">Brand accent (switch it in the header)</SubHead>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <TokenTile name="brand" desc="solid actions" swatch="var(--brand)" />
          <TokenTile name="brand-hover" desc="hover" swatch="var(--brand-hover)" />
          <TokenTile name="brand-text" desc="links, accent text" swatch="var(--brand-text)" />
          <TokenTile name="brand-subtle" desc="selected fills" swatch="var(--brand-subtle)" />
        </div>

        <SubHead className="mt-8">Status</SubHead>
        <div className="flex flex-wrap gap-2">
          <Badge variant="success">CPD accredited</Badge>
          <Badge variant="warning">Abstracts close in 11 days</Badge>
          <Badge variant="danger">Sold out</Badge>
          <Badge variant="info">Abstracts open</Badge>
          <Badge variant="neutral">Archived</Badge>
          <Badge variant="outline">Outline</Badge>
          <Badge variant="solid">Solid</Badge>
          <Badge variant="brand">Saved</Badge>
        </div>

        <SubHead className="mt-8">Event type &amp; format</SubHead>
        <div className="flex flex-wrap items-center gap-3">
          <EventTypeBadge type="conference" />
          <EventTypeBadge type="conference" isFlagship />
          <EventTypeBadge type="course" />
          <EventTypeBadge type="workshop" />
          <EventTypeBadge type="conference" isOnDemand />
          <Separator orientation="vertical" className="h-5" />
          <FormatBadge format="in_person" />
          <FormatBadge format="online" />
          <FormatBadge format="hybrid" />
        </div>
      </Section>

      {/* -------------------------------------------------------- TYPOGRAPHY */}
      <Section
        id="type"
        title="Typography"
        note="Figtree for display, Inter for body, JetBrains Mono for anything numeric or label-like. Hierarchy comes from weight and space, not colour."
      >
        <div className="space-y-6 rounded-lg border border-border bg-surface p-6">
          <Specimen step="display" meta="Figtree 600 · clamp 32–44px · -0.032em">
            <p className="type-display text-fg-strong">Find the CPD that fits your rota</p>
          </Specimen>
          <Specimen step="h1" meta="Figtree 600 · clamp 26–32px · -0.024em">
            <p className="type-h1 text-fg-strong">Conference directory</p>
          </Specimen>
          <Specimen step="h2" meta="Figtree 600 · 22px · -0.018em">
            <p className="type-h2 text-fg-strong">Closing soon</p>
          </Specimen>
          <Specimen step="h3" meta="Figtree 600 · 17px · -0.011em">
            <p className="type-h3 text-fg-strong">Registration &amp; fees</p>
          </Specimen>
          <Specimen step="body" meta="Inter 400 · 15px / 1.56">
            <p className="type-body text-fg">
              MedConf consolidates conferences, courses and CPD from 45 royal colleges, societies and
              international congresses into one directory. We do not take bookings — you register with the
              organiser.
            </p>
          </Specimen>
          <Specimen step="small" meta="Inter 400 · 14px">
            <p className="type-small text-fg-muted">Psychiatry · In person · Bristol, South West</p>
          </Specimen>
          <Specimen step="caption" meta="Inter 400 · 12px">
            <p className="type-caption text-fg-muted">Last checked 4 hours ago by the daily scrape.</p>
          </Specimen>
          <Specimen step="mono-label" meta="JetBrains Mono 500 · 11px · +0.07em uppercase">
            <p className="type-mono-label text-fg-muted">13 NOV · RCPSYCH · 5 CPD</p>
          </Specimen>
          <Specimen step="numeric" meta="JetBrains Mono · tabular figures">
            <div className="type-numeric space-y-0.5 text-fg">
              <div>£28</div>
              <div>£1,180</div>
              <div>$795</div>
            </div>
          </Specimen>
        </div>
      </Section>

      {/* ------------------------------------------------- RADIUS / SHADOW */}
      <Section id="shape" title="Shape &amp; elevation" note="6px is the default radius. Two shadow levels, both neutral — never a coloured glow.">
        <div className="flex flex-wrap gap-4">
          {(['xs', 'sm', 'md', 'lg', 'xl'] as const).map((r) => (
            <div key={r} className="text-center">
              <div
                className="size-16 border border-border bg-surface-muted"
                style={{ borderRadius: `var(--r-${r})` }}
              />
              <span className="mt-1.5 block type-mono-label text-fg-subtle">{r}</span>
            </div>
          ))}
          <Separator orientation="vertical" className="h-16" />
          {(['xs', 'sm', 'md'] as const).map((s) => (
            <div key={s} className="text-center">
              <div className="size-16 rounded-md border border-border bg-surface" style={{ boxShadow: `var(--sh-${s})` }} />
              <span className="mt-1.5 block type-mono-label text-fg-subtle">sh-{s}</span>
            </div>
          ))}
        </div>
      </Section>

      {/* ----------------------------------------------------------- BUTTONS */}
      <Section id="buttons" title="Buttons" note="Solid brand for the one primary action per view. Everything else is outline or ghost.">
        <div className="space-y-4 rounded-lg border border-border bg-surface p-5">
          {(['default', 'subtle', 'outline', 'secondary', 'ghost', 'destructive', 'link'] as const).map((variant) => (
            <div key={variant} className="flex flex-wrap items-center gap-3">
              <span className="w-24 shrink-0 type-mono-label text-fg-subtle">{variant}</span>
              <Button variant={variant} size="xs">Extra small</Button>
              <Button variant={variant} size="sm">Small</Button>
              <Button variant={variant}>Default</Button>
              <Button variant={variant} size="lg">Large</Button>
              <Button variant={variant}>
                <Filter /> With icon
              </Button>
              <Button variant={variant} disabled>Disabled</Button>
            </div>
          ))}
          <Separator />
          <div className="flex flex-wrap items-center gap-3">
            <span className="w-24 shrink-0 type-mono-label text-fg-subtle">icon</span>
            <Button size="icon-sm" variant="outline" aria-label="Filters"><SlidersHorizontal /></Button>
            <Button size="icon" variant="outline" aria-label="Filters"><SlidersHorizontal /></Button>
            <Button size="icon-lg" variant="outline" aria-label="Filters"><SlidersHorizontal /></Button>
            <Button size="icon" aria-label="Search"><Search /></Button>
          </div>
        </div>
      </Section>

      {/* -------------------------------------------------------- FORM & NAV */}
      <Section id="controls" title="Controls" note="Radix under everything — real keyboard and screen-reader behaviour, our tokens on top.">
        <div className="grid gap-5 lg:grid-cols-2">
          <Panel title="Input & select">
            <div className="space-y-3">
              <Input placeholder="Search by name, specialty or location…" aria-label="Search" />
              <Input placeholder="Disabled" disabled />
              <Input defaultValue="Not a valid date" aria-invalid />
              <Select>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Any region" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="london">London</SelectItem>
                  <SelectItem value="sw">South West</SelectItem>
                  <SelectItem value="nw">North West</SelectItem>
                  <SelectItem value="intl">International</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </Panel>

          <Panel title="Toggle group & tabs">
            <ToggleGroup type="single" defaultValue="any" variant="outline" className="w-full">
              <ToggleGroupItem value="any">Any</ToggleGroupItem>
              <ToggleGroupItem value="online">Online</ToggleGroupItem>
              <ToggleGroupItem value="in_person">In person</ToggleGroupItem>
              <ToggleGroupItem value="hybrid">Hybrid</ToggleGroupItem>
            </ToggleGroup>
            <Tabs defaultValue="consultant" className="mt-4">
              <TabsList variant="line">
                <TabsTrigger value="consultant">Consultant</TabsTrigger>
                <TabsTrigger value="trainee">Trainee</TabsTrigger>
                <TabsTrigger value="student">Student</TabsTrigger>
              </TabsList>
              <TabsContent value="consultant" className="pt-3 text-[0.8125rem] text-fg-muted">
                Early bird £185 · Standard £245
              </TabsContent>
              <TabsContent value="trainee" className="pt-3 text-[0.8125rem] text-fg-muted">
                Early bird £95 · Standard £135
              </TabsContent>
              <TabsContent value="student" className="pt-3 text-[0.8125rem] text-fg-muted">
                Free with proof of enrolment
              </TabsContent>
            </Tabs>
          </Panel>

          <Panel title="Overlays">
            <div className="flex flex-wrap gap-3">
              <Dialog>
                <DialogTrigger asChild>
                  <Button variant="outline">Dialog</Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Remove from saved?</DialogTitle>
                    <DialogDescription>
                      ESMO Congress 2027 will be removed from your saved list. Any reminders you set for it are
                      cancelled.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogFooter>
                    <Button variant="outline">Keep it</Button>
                    <Button variant="destructive">Remove</Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>

              <Sheet>
                <SheetTrigger asChild>
                  <Button variant="outline"><Filter /> Filters</Button>
                </SheetTrigger>
                <SheetContent side="right">
                  <SheetHeader>
                    <SheetTitle>Filters</SheetTitle>
                    <SheetDescription>The mobile filter surface W2 will build on.</SheetDescription>
                  </SheetHeader>
                  <div className="space-y-3 px-4">
                    <Input placeholder="Search societies…" />
                    <ToggleGroup type="multiple" variant="outline" className="w-full">
                      <ToggleGroupItem value="conference">Conference</ToggleGroupItem>
                      <ToggleGroupItem value="course">Course</ToggleGroupItem>
                      <ToggleGroupItem value="workshop">Workshop</ToggleGroupItem>
                    </ToggleGroup>
                  </div>
                </SheetContent>
              </Sheet>

              <Popover>
                <PopoverTrigger asChild>
                  <Button variant="outline">Popover</Button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0">
                  <Calendar mode="single" selected={date} onSelect={setDate} />
                </PopoverContent>
              </Popover>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline">Sort</Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  <DropdownMenuLabel>Sort by</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem><Check /> Date, soonest first</DropdownMenuItem>
                  <DropdownMenuItem>Price, lowest first</DropdownMenuItem>
                  <DropdownMenuItem>Recently added</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>

              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="outline">Tooltip</Button>
                </TooltipTrigger>
                <TooltipContent>Last scraped 4 hours ago</TooltipContent>
              </Tooltip>

              <Button variant="outline" onClick={() => toast.success('Saved to your list', { description: 'ESMO Congress 2027' })}>
                Toast
              </Button>
            </div>
          </Panel>

          <Panel title="Command (⌘K) & skeleton">
            <Command className="rounded-md border border-border">
              <CommandInput placeholder="Jump to a society or specialty…" />
              <CommandList>
                <CommandEmpty>No matches.</CommandEmpty>
                <CommandGroup heading="Specialties">
                  <CommandItem>Cardiology</CommandItem>
                  <CommandItem>Emergency Medicine</CommandItem>
                  <CommandItem>Psychiatry</CommandItem>
                </CommandGroup>
              </CommandList>
            </Command>
            <div className="mt-4 space-y-2.5">
              {[0, 1].map((i) => (
                <div key={i} className="flex items-center gap-4">
                  <Skeleton className="size-14 rounded-md" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-3.5 w-3/5" />
                    <Skeleton className="h-3 w-2/5" />
                  </div>
                  <Skeleton className="h-3.5 w-14" />
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </Section>

      {/* -------------------------------------------------------- PRIMITIVES */}
      <Section id="primitives" title="Domain primitives" note="Every state these hit in the real data, side by side.">
        <div className="grid gap-5 lg:grid-cols-2">
          <Panel title="DateBlock">
            <div className="flex flex-wrap items-end gap-4">
              <Labelled label="single day"><DateBlock startDate={iso(44)} /></Labelled>
              <Labelled label="range"><DateBlock startDate={iso(212)} endDate={iso(215)} /></Labelled>
              <Labelled label="crosses month"><DateBlock startDate={iso(60)} endDate={iso(64)} /></Labelled>
              <Labelled label="next year"><DateBlock startDate={iso(378)} /></Labelled>
              <Labelled label="no date"><DateBlock startDate={null} /></Labelled>
              <Labelled label="small"><DateBlock startDate={iso(44)} size="sm" /></Labelled>
            </div>
          </Panel>

          <Panel title="PriceLabel">
            <div className="flex flex-wrap items-center gap-6">
              <Labelled label="free"><PriceLabel min={0} size="md" /></Labelled>
              <Labelled label="exact"><PriceLabel min={720} max={720} size="md" /></Labelled>
              <Labelled label="from (GBP)"><PriceLabel min={28} max={208} size="md" /></Labelled>
              <Labelled label="USD"><PriceLabel min={795} max={1450} currency="USD" size="md" /></Labelled>
              <Labelled label="EUR"><PriceLabel min={640} max={1180} currency="EUR" size="md" /></Labelled>
              <Labelled label="unknown"><PriceLabel min={null} size="md" /></Labelled>
            </div>
          </Panel>

          <Panel title="CpdLabel & SocietyChip">
            <div className="flex flex-wrap items-center gap-6">
              <Labelled label="points known"><CpdLabel accredited points={12} size="md" /></Labelled>
              <Labelled label="accredited only"><CpdLabel accredited size="md" /></Labelled>
              <Labelled label="not accredited"><span className="text-[0.8125rem] text-fg-subtle">renders nothing</span></Labelled>
              <Labelled label="society"><SocietyChip name="RCPSYCH" /></Labelled>
            </div>
          </Panel>

          <Panel title="DeadlineBadge & SaveToggle">
            <div className="flex flex-wrap items-center gap-3">
              <DeadlineBadge deadline={iso(0)} />
              <DeadlineBadge deadline={iso(2)} />
              <DeadlineBadge deadline={iso(11)} />
              <DeadlineBadge deadline={iso(96)} />
              <DeadlineBadge deadline={null} note="see event page" />
              <DeadlineBadge deadline={iso(-5)} showClosed />
            </div>
            <div className="mt-4 flex items-center gap-4">
              <Labelled label="unsaved"><SaveToggle saved={false} onToggle={() => {}} /></Labelled>
              <Labelled label="saved"><SaveToggle saved onToggle={() => {}} /></Labelled>
            </div>
          </Panel>
        </div>
      </Section>

      {/* ---------------------------------------------------------- DIRECTORY */}
      <Section
        id="directory"
        title="Directory preview"
        note="Eight rows shaped like production data. Desktop uses EventRow; below 640px the same records render as EventCardCompact."
      >
        <SubHead>EventRow — desktop</SubHead>
        {/* EventRow is a >=640px component; on a phone the directory swaps to
            EventCardCompact. Here it scrolls rather than collapsing, so the
            narrow screenshots show the real row, not a squashed one. */}
        <div className="overflow-x-auto rounded-lg border border-border bg-surface">
          <div className="min-w-[640px]">
            {SAMPLE_EVENTS.map((e) => (
              <EventRow key={e.id} event={e} saved={!!saved[e.id]} onToggleSave={() => toggleSave(e.id)} />
            ))}
          </div>
        </div>

        <SubHead className="mt-8">EventCardCompact — mobile (shown at 390px)</SubHead>
        <div className="w-full max-w-[390px] space-y-2.5 rounded-lg border border-dashed border-border bg-bg p-3">
          {SAMPLE_EVENTS.slice(0, 5).map((e) => (
            <EventCardCompact key={e.id} event={e} saved={!!saved[e.id]} onToggleSave={() => toggleSave(e.id)} />
          ))}
        </div>
      </Section>
    </div>
  )
}

/* ------------------------------------------------------------------ chrome */

function Header() {
  return (
    <header className="sticky top-0 z-40 -mx-4 mb-10 border-b border-border bg-bg px-4 py-4 sm:-mx-6 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="type-mono-label text-fg-subtle">MedConf · W1</p>
          <h1 className="type-h1 mt-1 text-fg-strong">Design system</h1>
        </div>
        <div className="flex items-center gap-3">
          <AccentToggle />
          <Separator orientation="vertical" className="h-6" />
          <ThemeToggle className="border-border" />
        </div>
      </div>
      <p className="mt-3 max-w-2xl text-[0.8125rem] text-fg-muted">
        Not indexed, not linked from the site. Switch accent and theme above — every token, component and
        primitive below re-renders live.
      </p>
    </header>
  )
}

function Section({
  id,
  title,
  note,
  children,
}: {
  id: string
  title: string
  note?: string
  children: React.ReactNode
}) {
  return (
    <section id={id} className="scroll-mt-32 border-t border-border pt-10 pb-12 first-of-type:border-t-0 first-of-type:pt-0">
      <h2 className="type-h2 text-fg-strong">{title}</h2>
      {note && <p className="mt-1.5 max-w-3xl text-[0.8125rem] text-fg-muted">{note}</p>}
      <div className="mt-6">{children}</div>
    </section>
  )
}

function SubHead({ children, className }: { children: React.ReactNode; className?: string }) {
  return <h3 className={`type-mono-label mb-3 text-fg-subtle ${className ?? ''}`}>{children}</h3>
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-5">
      <h3 className="type-mono-label mb-4 text-fg-subtle">{title}</h3>
      {children}
    </div>
  )
}

function TokenTile({ name, desc, swatch }: { name: string; desc: string; swatch: string }) {
  return (
    <div className="overflow-hidden rounded-md border border-border">
      <div className="h-12" style={{ backgroundColor: swatch }} />
      <div className="bg-surface px-3 py-2">
        <div className="type-mono-label text-fg">{name}</div>
        <div className="mt-0.5 text-[0.75rem] text-fg-subtle">{desc}</div>
      </div>
    </div>
  )
}

function Specimen({ step, meta, children }: { step: string; meta: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-2 border-t border-border-subtle pt-5 first:border-t-0 first:pt-0 lg:grid-cols-[10rem_minmax(0,1fr)] lg:gap-6">
      <div>
        <div className="type-mono-label text-fg">{step}</div>
        <div className="mt-1 text-[0.75rem] leading-snug text-fg-subtle">{meta}</div>
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

function Labelled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2 type-mono-label text-fg-subtle">{label}</div>
      {children}
    </div>
  )
}

function iso(days: number): string {
  const d = new Date()
  d.setHours(12, 0, 0, 0)
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}
