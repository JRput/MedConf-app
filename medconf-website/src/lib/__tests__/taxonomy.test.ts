import { describe, expect, it } from 'vitest'
import { canonicalSpecialty, rawValuesForParent, RAW_TO_CANONICAL, SPECIALTY_PARENTS } from '../taxonomy/specialties'
import { classifyPriceBucket } from '../directory-query'
import { SOCIETIES, societyInfo } from '../taxonomy/societies'

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

  it('every entry has a non-empty full name distinct from its short code', () => {
    for (const info of Object.values(SOCIETIES)) {
      expect(info.name.length).toBeGreaterThan(info.short.length)
    }
  })
})
