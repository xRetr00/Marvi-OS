import { describe, expect, it } from 'vitest'

import { metaValue, toChatMessage } from './types'

describe('toChatMessage', () => {
  it('keeps known roles', () => {
    expect(toChatMessage({ id: 1, at: '', role: 'user', content: '', meta: {} }).role).toBe('user')
    expect(toChatMessage({ id: 1, at: '', role: 'assistant', content: '', meta: {} }).role).toBe(
      'assistant'
    )
    expect(toChatMessage({ id: 1, at: '', role: 'tool', content: '', meta: {} }).role).toBe('tool')
  })

  it('maps unknown roles to error', () => {
    expect(toChatMessage({ id: 1, at: '', role: 'banana', content: '', meta: {} }).role).toBe(
      'error'
    )
  })
})

describe('metaValue', () => {
  it('reads strings and numbers', () => {
    expect(metaValue({ tool: 'file_read' }, 'tool')).toBe('file_read')
    expect(metaValue({ tokens: 12 }, 'tokens')).toBe('12')
  })

  it('returns empty for missing or non-scalar values', () => {
    expect(metaValue({}, 'tool')).toBe('')
    expect(metaValue({ tool: { nested: true } }, 'tool')).toBe('')
  })
})
