import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { EventTypeBadge } from '@/components/domain/EventTypeBadge'
import { parseDirectoryUrl, serializeDirectoryFilters } from '../directory-url'
import { DEFAULT_FILTERS } from '../directory-query'

describe('degree event type', () => {
  it('badge renders "Degree" with its own token colours', () => {
    const html = renderToStaticMarkup(<EventTypeBadge type="degree" />)
    expect(html).toContain('Degree')
    expect(html).toContain('type-degree')
    expect(html).not.toContain('Conference')
  })

  it('type=degree round-trips through the URL', () => {
    const f = parseDirectoryUrl('type=degree,course')
    expect(f.type).toEqual(['degree', 'course'])
    const again = parseDirectoryUrl(serializeDirectoryFilters(f))
    expect(again.type).toEqual(['degree', 'course'])
  })

  it('an unknown type is dropped safely', () => {
    expect(parseDirectoryUrl('type=symposium').type).toEqual(DEFAULT_FILTERS.type)
  })
})
