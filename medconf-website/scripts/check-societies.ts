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
const { data, error } = await sb.from('directory_events').select('society')
if (error) { console.error(error.message); process.exit(2) }
const codes = [...new Set((data ?? []).map((r) => r.society).filter(Boolean))]
const missing = codes.filter((c) => !SOCIETIES[c as string])
if (missing.length) { console.error('Missing from taxonomy/societies.ts:', missing); process.exit(1) }
console.log(`OK — all ${codes.length} society codes mapped`)
}
main()
