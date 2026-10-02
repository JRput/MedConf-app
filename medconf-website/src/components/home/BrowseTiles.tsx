// src/components/home/BrowseTiles.tsx
//
// The quiet tile used by both "Browse by specialty" and "Browse by society".
// Same shape as the tiles on /societies so the two pages read as one product;
// flat surface, one hairline, a count that is a real facet count (never a
// rounded-up marketing number) and nothing else.

import Link from 'next/link'

export interface BrowseTile {
  href: string
  label: string
  /** Second line — the full society name, or the country. Optional. */
  sub?: string
  count: number
}

export function BrowseTiles({ tiles, columns = 4 }: { tiles: BrowseTile[]; columns?: 3 | 4 }) {
  return (
    <div
      className={
        columns === 3
          ? 'grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3'
          : 'grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4'
      }
    >
      {tiles.map((tile) => (
        <Link
          key={tile.href}
          href={tile.href}
          className="group flex min-h-[4.25rem] flex-col justify-center gap-0.5 rounded-lg border border-border bg-surface px-3.5 py-3 transition-colors duration-150 hover:border-border-strong hover:bg-surface-hover"
        >
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-[0.9375rem] font-medium leading-snug text-fg-strong transition-colors duration-150 group-hover:text-brand-text">
              {tile.label}
            </span>
            <span className="type-numeric shrink-0 text-[0.8125rem] text-fg-subtle">{tile.count}</span>
          </div>
          {tile.sub && <span className="truncate text-[0.8125rem] text-fg-muted">{tile.sub}</span>}
        </Link>
      ))}
    </div>
  )
}
