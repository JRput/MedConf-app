// src/lib/community/normalize-url.ts
// URL hygiene for community submissions (board §2). The normalised form is
// what gets stored and what the duplicate check compares, so two users
// pasting the same organiser page with different tracking junk collide.

const TRACKING_PARAM = /^(utm_.*|fbclid|gclid)$/i

/**
 * Lower-case scheme+host, drop fragment, drop utm_* / fbclid / gclid, drop the
 * trailing slash on non-root paths, keep other query params. Credentials in
 * the URL are stripped. Returns null for anything that is not a valid http(s)
 * URL.
 */
export function normalizeUrl(input: string | null | undefined): string | null {
  if (typeof input !== 'string') return null
  const trimmed = input.trim()
  if (!trimmed) return null

  let url: URL
  try {
    url = new URL(trimmed)
  } catch {
    return null
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null
  if (!url.hostname) return null

  url.hash = ''
  url.username = ''
  url.password = ''

  const kept: [string, string][] = []
  url.searchParams.forEach((value, key) => {
    if (!TRACKING_PARAM.test(key)) kept.push([key, value])
  })
  if (kept.length === 0) {
    url.search = ''
  } else if (kept.length !== Array.from(url.searchParams.keys()).length) {
    url.search = new URLSearchParams(kept).toString()
  }

  if (url.pathname.length > 1 && url.pathname.endsWith('/')) {
    url.pathname = url.pathname.replace(/\/+$/, '') || '/'
  }

  return url.toString()
}

function hostOf(input: string): string | null {
  const n = normalizeUrl(input)
  if (!n) return null
  return new URL(n).hostname.toLowerCase().replace(/^www\./, '')
}

/** True when both URLs are valid and share a hostname (ignoring a leading www.). */
export function sameDomain(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return false
  const ha = hostOf(a)
  const hb = hostOf(b)
  return ha !== null && ha === hb
}
