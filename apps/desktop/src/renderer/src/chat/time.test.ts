import { describe, expect, it } from 'vitest'

import { formatRelative, formatTime, titleFromMessages } from './time'

describe('formatTime', () => {
  it('renders hour:minute', () => {
    expect(formatTime('2026-08-17T14:05:00Z')).toMatch(/^\d{2}:\d{2}$/)
  })

  it('returns empty for invalid dates', () => {
    expect(formatTime('nope')).toBe('')
  })
})

describe('formatRelative', () => {
  const now = Date.UTC(2026, 7, 17, 12, 0, 0)

  it('says now for under a minute', () => {
    expect(formatRelative('2026-08-17T11:59:40Z', now)).toBe('now')
  })

  it('counts minutes', () => {
    expect(formatRelative('2026-08-17T11:50:00Z', now)).toBe('10m ago')
  })

  it('counts hours', () => {
    expect(formatRelative('2026-08-17T08:00:00Z', now)).toBe('4h ago')
  })

  it('counts days', () => {
    expect(formatRelative('2026-08-15T12:00:00Z', now)).toBe('2d ago')
  })

  it('returns empty for invalid dates', () => {
    expect(formatRelative('nope', now)).toBe('')
  })
})

describe('titleFromMessages', () => {
  it('uses the first user message', () => {
    expect(titleFromMessages([{ role: 'user', content: 'Summarize my day' }])).toBe(
      'Summarize my day'
    )
  })

  it('ignores assistant-only history', () => {
    expect(titleFromMessages([{ role: 'assistant', content: 'hello' }])).toBe('New chat')
  })

  it('truncates long titles with an ellipsis', () => {
    const title = titleFromMessages([{ role: 'user', content: 'x'.repeat(120) }])
    expect(title.endsWith('…')).toBe(true)
    expect(title.length).toBeLessThanOrEqual(43)
  })

  it('takes only the first line', () => {
    expect(titleFromMessages([{ role: 'user', content: 'first\nsecond' }])).toBe('first')
  })
})
