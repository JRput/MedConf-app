// Build-time loader for the legal documents in <repo>/legal/<slug>.md.
// Server-only (uses fs). The Markdown is our own file, so the HTML is trusted.
import fs from 'node:fs'
import path from 'node:path'
import { marked } from 'marked'
import { SITE_NAME, CONTACT_EMAIL } from '@/lib/site'

export type LegalSlug = 'terms' | 'privacy' | 'cookies'
export interface LegalDoc {
  title: string
  lastUpdated: string
  html: string
}

const PLACEHOLDER = /\[\[PLACEHOLDER:\s*([\s\S]*?)\]\]/g

function readSource(slug: string): string {
  // Local: cwd = medconf-website, legal/ is one level up. Vercel root dir is
  // medconf-website too, but also try cwd itself in case legal/ is bundled.
  const candidates = [
    path.resolve(process.cwd(), '..', 'legal', `${slug}.md`),
    path.resolve(process.cwd(), 'legal', `${slug}.md`),
  ]
  for (const p of candidates) if (fs.existsSync(p)) return fs.readFileSync(p, 'utf8')
  throw new Error(`legal document not found: ${slug}.md`)
}

function frontMatterValue(fm: string, key: string): string {
  const m = fm.match(new RegExp(`^${key}:\\s*(.*)$`, 'm'))
  if (!m) return ''
  return m[1].trim().replace(/^"(.*)"$/, '$1').replace(/^'(.*)'$/, '$1')
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** Pure transform, exported for tests. */
export function renderLegal(raw: string): LegalDoc {
  let body = raw.replace(/\r\n/g, '\n')
  let fm = ''
  const m = body.match(/^---\n([\s\S]*?)\n---\n?/)
  if (m) {
    fm = m[1]
    body = body.slice(m[0].length)
  }
  body = body.replace(/<!--[\s\S]*?-->/g, '')
  body = body.replace(/hellomedicon@gmail\.com/g, CONTACT_EMAIL).replace(/MediCon/g, SITE_NAME)
  // Placeholders become a visible marker; the token survives Markdown parsing.
  body = body.replace(PLACEHOLDER, (_all, inner: string) => `<mark data-placeholder>[[PLACEHOLDER: ${escapeHtml(inner.trim())}]]</mark>`)

  let html = marked.parse(body, { async: false, gfm: true }) as string
  html = html.replace(/<table>/g, '<div class="legal-table"><table>').replace(/<\/table>/g, '</table></div>')

  let lastUpdated = frontMatterValue(fm, 'last_updated')
  lastUpdated = lastUpdated.replace(PLACEHOLDER, (_a, inner: string) => `[[PLACEHOLDER: ${inner.trim()}]]`)
  return { title: frontMatterValue(fm, 'title'), lastUpdated, html }
}

export function loadLegal(slug: LegalSlug): LegalDoc {
  return renderLegal(readSource(slug))
}
