import type { LegalDoc } from '@/lib/legal'

// Styles for the rendered Markdown. Scoped to .legal-prose; tokens come from globals.css.
const CSS = `
.legal-prose { color: var(--fg); font-size: 0.9375rem; line-height: 1.65; overflow-wrap: anywhere; }
.legal-prose h1 { font-family: var(--font-display); font-size: clamp(1.625rem, 1.3rem + 1.1vw, 2rem); line-height: 1.14; letter-spacing: -0.024em; font-weight: 600; color: var(--fg-strong); margin: 0 0 1rem; }
.legal-prose h2 { font-family: var(--font-display); font-size: 1.375rem; line-height: 1.22; letter-spacing: -0.018em; font-weight: 600; color: var(--fg-strong); margin: 2.25rem 0 0.75rem; }
.legal-prose h3 { font-family: var(--font-display); font-size: 1.0625rem; line-height: 1.32; font-weight: 600; color: var(--fg-strong); margin: 1.5rem 0 0.5rem; }
.legal-prose p, .legal-prose ul, .legal-prose ol, .legal-prose blockquote { margin: 0.75rem 0; }
.legal-prose ul { list-style: disc; padding-left: 1.4rem; }
.legal-prose ol { list-style: decimal; padding-left: 1.4rem; }
.legal-prose li { margin: 0.3rem 0; }
.legal-prose a { color: var(--brand); text-decoration: underline; text-underline-offset: 2px; }
.legal-prose strong { color: var(--fg-strong); font-weight: 600; }
.legal-prose blockquote { border-left: 3px solid var(--border); padding-left: 1rem; color: var(--fg-muted); }
.legal-prose hr { border: 0; border-top: 1px solid var(--border); margin: 2rem 0; }
.legal-prose code { font-family: var(--font-mono); font-size: 0.85em; }
.legal-prose mark[data-placeholder] { background: #fde68a; color: #1f2937; padding: 0 0.25em; border-radius: 3px; }
.legal-prose .legal-table { overflow-x: auto; margin: 1rem 0; -webkit-overflow-scrolling: touch; }
.legal-prose table { border-collapse: collapse; min-width: 32rem; width: 100%; font-size: 0.8125rem; }
.legal-prose th, .legal-prose td { border: 1px solid var(--border); padding: 0.5rem 0.65rem; text-align: left; vertical-align: top; }
.legal-prose th { background: var(--bg-subtle, transparent); color: var(--fg-strong); font-weight: 600; }
`

/** Shared shell for the three legal pages. */
export function LegalPage({ doc }: { doc: LegalDoc }) {
  return (
    <main className="mx-auto w-full max-w-[760px] px-4 py-10 sm:px-6 sm:py-14">
      <style dangerouslySetInnerHTML={{ __html: CSS }} />
      <article className="legal-prose" dangerouslySetInnerHTML={{ __html: doc.html }} />
    </main>
  )
}
