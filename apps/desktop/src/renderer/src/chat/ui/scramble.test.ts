import { describe, expect, it } from 'vitest'

import { scrambleFrame } from './scramble'

/**
 * The label settles into its words; it does not churn forever and it does not
 * lose the shape of the sentence on the way. Both are invisible in a diff and
 * obvious on screen.
 */
describe('scrambleFrame', () => {
  const steady = (): number => 0

  it('reveals the settled prefix in order', () => {
    expect(scrambleFrame('Marvi', 3, steady).slice(0, 3)).toBe('Mar')
  })

  it('finishes as the real text once everything is revealed', () => {
    expect(scrambleFrame('Marvi is thinking', 99, steady)).toBe('Marvi is thinking')
  })

  it('keeps the spaces so it still reads as a sentence mid-scramble', () => {
    const frame = scrambleFrame('Marvi is thinking', 0, steady)
    expect(frame.length).toBe('Marvi is thinking'.length)
    expect([...frame].map((c, i) => (c === ' ' ? i : -1)).filter((i) => i >= 0)).toEqual([5, 8])
  })

  it('never emits a settled character early', () => {
    const frame = scrambleFrame('abc', 0, steady)
    expect(frame).not.toContain('a')
    expect(frame).not.toContain('b')
  })

  it('draws its noise from Marvi’s own glyphs, not random letters', () => {
    const frame = scrambleFrame('xxxx', 0, () => 0.99)
    expect(/^[▁▂▃▄▅▆▇█▓▒░╱╲┃┊·]+$/u.test(frame)).toBe(true)
  })
})
