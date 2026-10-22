import { describe, expect, it } from 'vitest'
import { canonicalSpecialty, rawValuesForParent, RAW_TO_CANONICAL, SPECIALTY_PARENTS } from '../taxonomy/specialties'
import { classifyPriceBucket } from '../directory-query'
import { SOCIETIES, societyInfo, societiesByKind } from '../taxonomy/societies'

describe('specialty taxonomy', () => {
  // 10 deliberately tricky raw values from the live data pull (near-
  // duplicates, spelling variants, a non-Latin script value, and an
  // ambiguous standalone "General") — see
  // ../../../reports/website-audit/data.md §5.
  const tricky: Array<[string, string]> = [
    ['Obstetrics and Gynecology', 'obgyn-womens-health'], // US spelling variant of the UK "Obstetrics & Gynaecology"
    ['Obstetrics & Gynaecology', 'obgyn-womens-health'],
    ['Surgery (RCS)', 'surgery-general'], // parenthetical variant
    ['Minor Surgery & Procedures', 'surgery-general'],
    ['Otolaryngology (ENT)', 'ent-otolaryngology'],
    ['心血管内科', 'cardiology'], // Chinese for Cardiovascular Medicine
    ['Medical Leadership', 'leadership-management'], // merges with "Leadership & Management"
    ['Leadership & Management', 'leadership-management'],
    ['Geriatrics', 'geriatric-medicine'], // singular/plural variant of "Geriatric Medicine"
    ['Palliative Care', 'palliative-rehabilitation'], // vs "Palliative Medicine"
  ]

  it.each(tricky)('%s -> %s', (raw, expectedParent) => {
    expect(canonicalSpecialty(raw).parent).toBe(expectedParent)
  })

  it('falls back to "other" for null/unknown values rather than throwing', () => {
    expect(canonicalSpecialty(null).parent).toBe('other')
    expect(canonicalSpecialty(undefined).parent).toBe('other')
    expect(canonicalSpecialty('Something Brand New The Scraper Just Found').parent).toBe('other')
  })

  it('is case-insensitive', () => {
    expect(canonicalSpecialty('oncology').parent).toBe('oncology')
    expect(canonicalSpecialty('ONCOLOGY').parent).toBe('oncology')
  })

  it('rawValuesForParent is the exact inverse of RAW_TO_CANONICAL', () => {
    for (const parent of SPECIALTY_PARENTS) {
      const raws = rawValuesForParent(parent.slug)
      for (const raw of raws) {
        expect(RAW_TO_CANONICAL[raw]).toBe(parent.slug)
      }
    }
    // every mapped raw value must appear in exactly one parent's reverse list
    const allMapped = Object.keys(RAW_TO_CANONICAL)
    const coveredByReverse = SPECIALTY_PARENTS.flatMap((p) => rawValuesForParent(p.slug))
    expect(new Set(coveredByReverse)).toEqual(new Set(allMapped))
  })

  it('every parent label canonicalises to its own slug (G1: stored label must round-trip)', () => {
    for (const p of SPECIALTY_PARENTS) {
      expect(RAW_TO_CANONICAL[p.label], p.label).toBe(p.slug)
      expect(canonicalSpecialty(p.label).parent, p.label).toBe(p.slug)
      expect(rawValuesForParent(p.slug)).toContain(p.label)
    }
  })

  it('every value in RAW_TO_CANONICAL points at a real parent slug', () => {
    const validSlugs = new Set(SPECIALTY_PARENTS.map((p) => p.slug))
    for (const parent of Object.values(RAW_TO_CANONICAL)) {
      expect(validSlugs.has(parent)).toBe(true)
    }
  })
})

describe('price bucket semantics (unknown pricing is never "free")', () => {
  it('null (no pricing_tiers row at all) is "unknown", not "free"', () => {
    expect(classifyPriceBucket(null)).toBe('unknown')
  })
  it('0 is genuinely free', () => {
    expect(classifyPriceBucket(0)).toBe('free')
  })
  it('boundaries are half-open on the upper bound', () => {
    expect(classifyPriceBucket(99.99)).toBe('under-100')
    expect(classifyPriceBucket(100)).toBe('under-300')
    expect(classifyPriceBucket(299.99)).toBe('under-300')
    expect(classifyPriceBucket(300)).toBe('over-300')
  })
})

describe('societies taxonomy', () => {
  it('covers every active source society code seen live (2026-10-02 pull)', () => {
    const expected = [
      'RCGP', 'RCSEng', 'RSM', 'RCP', 'RCEM', 'RCOG', 'RCR', 'BOPA', 'BTOG',
      'ASCO', 'ESMO', 'AACR', 'ESTRO', 'SABCS', 'ESGO', 'SITC', 'ALSG',
      'RCPSG', 'RCPath', 'RCPsych', 'RCSEd', 'Resus Council UK', 'RCPE',
      'RCPCH', 'RCOphth', 'FPH', 'FOM', 'FPM', 'ESC', 'ACPGBI', 'ASGBI',
      'CoSRH', 'FICM', 'ARVO', 'IAS', 'MDDUS', 'MDU',
    ]
    for (const code of expected) {
      expect(societyInfo(code), `missing society: ${code}`).not.toBeNull()
    }
  })

  it('falls back to a usable record for an unknown code instead of null', () => {
    const info = societyInfo('NOT-A-REAL-SOCIETY')
    expect(info).not.toBeNull()
    expect(info?.name).toBe('NOT-A-REAL-SOCIETY')
    expect(info?.kind).toBe('other')
  })

  it('every entry has a non-empty full name that is never shorter than its short code', () => {
    // A single-word society (e.g. "Endocrine Society") legitimately has
    // name === short, so equality is allowed; only an empty or truncated
    // name is a data error.
    for (const [key, info] of Object.entries(SOCIETIES)) {
      expect(info.name.trim().length, key).toBeGreaterThan(0)
      expect(info.name.length, key).toBeGreaterThanOrEqual(info.short.length)
      expect(info.short, key).toBe(key)
    }
  })

  it('has a Community pseudo-society for user-submitted events', () => {
    expect(societyInfo('Community')?.name).toBe('Community submissions')
  })
})

describe('wave 2d societies and runtime fallback', () => {
  const wave2d: Array<[string, string]> = [
    ...['EAN', 'AAIC', 'AUA', 'AAO', 'RSNA', 'CHEST', 'ACC', 'ASN', 'ASA', 'UEG', 'ESCRS', 'EULAR', 'PCR', 'SIU', 'ESHRE', 'ASH'].map((k): [string, string] => [k, 'international']),
    ...['BOFAS', 'BPNA', 'BAAPS', 'BSSH', 'Vascular Society', 'BAUS', 'HIS', 'BBTS', 'ABS', 'BASL', 'BSIR', 'BMFMS', 'BTS', 'BSR', 'BAPM', 'SBNS', 'BSG', 'BOA', 'ICS', 'AUGIS'].map((k): [string, string] => [k, 'specialist']),
  ]

  it('resolves every wave 2d key with the right kind', () => {
    expect(wave2d).toHaveLength(36)
    for (const [code, kind] of wave2d) {
      expect(SOCIETIES[code], `not in SOCIETIES: ${code}`).toBeDefined()
      expect(societyInfo(code)?.kind, code).toBe(kind)
    }
  })

  it('adds unmapped facet codes under other, without duplicates or pseudo buckets', () => {
    const g = societiesByKind(['ZZZ New Society', 'BOA', 'unspecified', 'Community'])
    const all = Object.values(g).flat()
    expect(g.other.find((s) => s.short === 'ZZZ New Society')?.name).toBe('ZZZ New Society')
    expect(all.filter((s) => s.short === 'BOA')).toHaveLength(1)
    expect(all.some((s) => s.short === 'unspecified')).toBe(false)
    expect(all.filter((s) => s.short === 'Community')).toHaveLength(1) // only the SOCIETIES pseudo entry
    expect(g.other.some((s) => s.short === 'unspecified')).toBe(false)
  })

  it('with no argument returns exactly the SOCIETIES entries', () => {
    expect(Object.values(societiesByKind()).flat()).toHaveLength(Object.keys(SOCIETIES).length)
  })
})
