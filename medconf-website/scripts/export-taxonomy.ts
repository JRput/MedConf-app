// scripts/export-taxonomy.ts
//
// Generates src/lib/taxonomy/specialties.json from specialties.ts, which
// stays the SOURCE OF TRUTH — this script is the only thing that writes
// the JSON, so TS and JSON can never drift as long as this is re-run after
// editing specialties.ts (`npm run taxonomy:export`).
//
// Why a generated JSON file at all: medconf-scraper/fire_specialty_alerts.py
// (Python, no TS toolchain) needs the same raw-specialty -> canonical-parent
// map so a user's stored `specialty` (now a canonical parent slug per W6
// onboarding, see medconf-scraper/specialty_taxonomy.py) expands to every
// matching raw `conferences.specialty` value before querying. Rather than
// hand-maintaining a second copy in Python, the website's TS map is
// exported once to a plain JSON file both runtimes can read.
//
// Run: npm run taxonomy:export (from medconf-website/)

import { writeFileSync } from 'node:fs'
import path from 'node:path'
import { SPECIALTY_PARENTS, RAW_TO_CANONICAL } from '../src/lib/taxonomy/specialties'

const OUT_PATH = path.resolve(__dirname, '../src/lib/taxonomy/specialties.json')

const payload = {
  // Bumped only if the shape of this file changes in a way consumers need
  // to branch on; the map CONTENTS change freely without bumping this.
  schemaVersion: 1,
  generatedAt: new Date().toISOString().slice(0, 10),
  generatedBy: 'scripts/export-taxonomy.ts (npm run taxonomy:export) — do not hand-edit',
  parents: SPECIALTY_PARENTS,
  rawToCanonical: RAW_TO_CANONICAL,
}

writeFileSync(OUT_PATH, JSON.stringify(payload, null, 2) + '\n', 'utf-8')
console.log(`Wrote ${Object.keys(RAW_TO_CANONICAL).length} raw->parent mappings, ${SPECIALTY_PARENTS.length} parents -> ${OUT_PATH}`)
