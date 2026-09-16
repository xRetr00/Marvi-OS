import { describe, expect, it } from 'vitest'

import { completeMention, trailingMention } from './mention'

describe('completing an @ mention', () => {
  it('sees the mention being typed at the end', () => {
    expect(trailingMention('summarise @no')).toEqual({ query: 'no', at: 10 })
    expect(trailingMention('@')).toEqual({ query: '', at: 0 })
  })

  it('ignores anything that is not a mention in progress', () => {
    expect(trailingMention('summarise @notes.md please')).toBeNull() // already finished
    expect(trailingMention('mail me@example.com')).toBeNull() // not a mention
    expect(trailingMention('')).toBeNull()
  })

  it('replaces what was typed and quotes a path with spaces', () => {
    const text = 'summarise @no'
    expect(completeMention(text, trailingMention(text)!, 'notes.md')).toBe('summarise @notes.md ')
    expect(completeMention(text, trailingMention(text)!, 'two words.md')).toBe(
      'summarise @"two words.md" '
    )
  })
})
