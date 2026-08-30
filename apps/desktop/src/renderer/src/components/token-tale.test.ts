import { describe, expect, it } from 'vitest'

import { tokenTale } from './token-tale'

describe('tokenTale', () => {
  it('has an honest empty state', () => {
    expect(tokenTale(0).lead).toBe('The library card is untouched.')
  })

  it('moves through book scales as visible usage grows', () => {
    expect(tokenTale(123_000).lead).toContain('The Hobbit')
    expect(tokenTale(575_000).lead).toContain('The Lord of the Rings trilogy')
    expect(tokenTale(2_900_000).lead).toContain('2.00×')
    expect(tokenTale(2_900_000).lead).toContain('Harry Potter')
  })
})
