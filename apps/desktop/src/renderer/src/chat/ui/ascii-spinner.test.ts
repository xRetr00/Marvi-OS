import { describe, expect, it } from 'vitest'

import { SPINNER_FRAMES, pulseSequence } from './ascii-spinner'

/**
 * The only thing here worth asserting is the frame order, because getting it
 * wrong is invisible in a diff and obvious on screen: a sequence that runs
 * forward only snaps from the largest glyph back to a dot every cycle, which
 * reads as a stutter rather than a pulse.
 */
describe('pulseSequence', () => {
  it('runs forward then back without repeating either end', () => {
    expect(pulseSequence(5)).toEqual([0, 1, 2, 3, 4, 3, 2, 1])
  })

  it('never leaves the frame list', () => {
    for (const index of pulseSequence(SPINNER_FRAMES.length)) {
      expect(SPINNER_FRAMES[index]).toBeTypeOf('string')
    }
  })

  it('uses Claude Code’s five glyphs, smallest first', () => {
    expect([...SPINNER_FRAMES]).toEqual(['·', '✢', '✳', '✶', '✽'])
  })

  it('degrades to a single frame rather than an empty cycle', () => {
    expect(pulseSequence(1)).toEqual([0])
  })
})
