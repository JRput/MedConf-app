import { describe, it, expect } from 'vitest'
import { renderLegal, loadLegal } from '../legal'
import { SITE_NAME, CONTACT_EMAIL } from '../site'

const RAW = `---
title: Terms of Use
last_updated: "[[PLACEHOLDER: publication date]]"
---

<!-- DRAFT NOTES hidden -->
# Terms of Use

Welcome to MediCon. Write to hellomedicon@gmail.com. Run by [[PLACEHOLDER: operator name]].

| A | B |
|---|---|
| 1 | 2 |
`

describe('renderLegal', () => {
  const doc = renderLegal(RAW)
  it('strips front-matter and comments, reads title', () => {
    expect(doc.title).toBe('Terms of Use')
    expect(doc.html).not.toContain('DRAFT NOTES')
    expect(doc.html).not.toContain('title:')
  })
  it('replaces brand and email', () => {
    expect(doc.html).not.toContain('MediCon')
    expect(doc.html).toContain(`Welcome to ${SITE_NAME}`)
    expect(doc.html).toContain(CONTACT_EMAIL)
  })
  it('marks placeholders visibly', () => {
    expect(doc.html).toContain('<mark data-placeholder>[[PLACEHOLDER: operator name]]</mark>')
  })
  it('wraps tables in a scroll container', () => {
    expect(doc.html).toContain('<div class="legal-table"><table>')
    expect(doc.html).toContain('</table></div>')
  })
})

describe('loadLegal', () => {
  it.each(['terms', 'privacy', 'cookies'] as const)('loads %s from the repo legal dir', slug => {
    const d = loadLegal(slug)
    expect(d.title).not.toBe('')
    expect(d.html).not.toContain('<!--')
    expect(d.html).not.toContain('MediCon')
  })
})
