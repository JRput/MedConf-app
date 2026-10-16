// Fails if scraper_sources has an active society code missing from taxonomy/societies.ts.
// Run: npm run check:societies  (uses NEXT_PUBLIC_SUPABASE_URL/ANON_KEY from .env.local)
import { createClient } from '@supabase/supabase-js'
import { readFileSync } from 'node:fs'
import { SOCIETIES } from '../src/lib/taxonomy/societies'

for (const line of readFileSync('.env.local', 'utf8').split('\n')) {
  const m = line.match(/^([A-Z_]+)=(.*)$/); if (m && !process.env[m[1]]) process.env[m[1]] = m[2]
}
async function main() {
const sb = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!)
// Society codes come from the `directory_facets` RPC (the same aggregate the
// home page counts), not a row select: PostgREST caps a select at 1000 rows,
// and on 2026-10-16 that hid 11 of the 18 newest societies from this check.
const { data, error } = await sb.rpc('directory_facets', {
  p_q: null, p_date_from: null, p_date_to: null, p_format: null, p_type: null,
  p_specialty_raw: null, p_region: null, p_country: null, p_price: null,
  p_society: null, p_cpd: null, p_abstracts_open: null,
})
if (error) { console.error(error.message); process.exit(2) }
const codes = Object.keys(((data ?? {}) as { society?: Record<string, number> }).society ?? {})
const missing = codes.filter((c) => !SOCIETIES[c as string])
if (missing.length) { console.error('Missing from taxonomy/societies.ts:', missing); process.exit(1) }
console.log(`OK — all ${codes.length} society codes mapped`)
}
main()
