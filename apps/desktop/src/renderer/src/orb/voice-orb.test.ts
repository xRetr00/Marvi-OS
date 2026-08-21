import { describe, expect, it } from 'vitest'

import { MOOD_FOR_PHASE, RAMPS, blend } from './moods'
import { coherentWaveScale } from './wave'

describe('orb mood', () => {
  it('gives every live phase its own colour', () => {
    // The orb is the fastest signal on the page: you catch colour across a
    // room and you have to be looking at text to read a label.
    const moods = new Set(
      ['listening', 'wake', 'thinking', 'speaking', 'error'].map((p) => MOOD_FOR_PHASE[p])
    )
    expect(moods.size).toBe(4) // wake shares listening's colour, deliberately
    for (const mood of moods) expect(RAMPS[mood]).toBeDefined()
  })

  it('rests on idle for a phase it does not know', () => {
    expect(MOOD_FOR_PHASE['ready']).toBeUndefined()
    expect(MOOD_FOR_PHASE['something-new']).toBeUndefined()
  })

  it('keeps error unmistakable — no working state may share its colour', () => {
    const errorNear = blend(RAMPS.error, RAMPS.error, 1, 1)
    for (const mood of ['idle', 'listening', 'thinking', 'speaking']) {
      const other = blend(RAMPS[mood], RAMPS[mood], 1, 1)
      expect(other).not.toEqual(errorNear)
    }
  })
})

describe('voice-driven wave', () => {
  const point = [0.62, 0.35, -0.7] as const

  it('is motionless without audio energy', () => {
    expect(coherentWaveScale(point, 0, 0)).toBe(1)
    expect(coherentWaveScale(point, 100, 0)).toBe(1)
  })

  it('is deterministic and bounded', () => {
    const first = coherentWaveScale(point, 2.4, 0.8)
    expect(coherentWaveScale(point, 2.4, 0.8)).toBe(first)
    expect(first).toBeGreaterThanOrEqual(0.86)
    expect(first).toBeLessThanOrEqual(1.14)
  })

  it('moves as a travelling field when voice advances it', () => {
    expect(coherentWaveScale(point, 0.5, 0.9)).not.toBe(coherentWaveScale(point, 1.5, 0.9))
  })
})

describe('mood crossfade', () => {
  it('is the source at nought and the destination at one', () => {
    const from = blend(RAMPS.listening, RAMPS.speaking, 0, 0.5)
    const to = blend(RAMPS.listening, RAMPS.speaking, 1, 0.5)

    expect(from).toEqual(blend(RAMPS.listening, RAMPS.listening, 1, 0.5))
    expect(to).toEqual(blend(RAMPS.speaking, RAMPS.speaking, 1, 0.5))
  })

  it('passes through the middle rather than jumping', () => {
    // A phase change that snapped would read as a glitch, not a state change.
    const from = blend(RAMPS.listening, RAMPS.speaking, 0, 0.8)
    const half = blend(RAMPS.listening, RAMPS.speaking, 0.5, 0.8)
    const to = blend(RAMPS.listening, RAMPS.speaking, 1, 0.8)

    for (let channel = 0; channel < 3; channel += 1) {
      const low = Math.min(from[channel], to[channel])
      const high = Math.max(from[channel], to[channel])
      expect(half[channel]).toBeGreaterThanOrEqual(low)
      expect(half[channel]).toBeLessThanOrEqual(high)
    }
  })

  it('produces a real colour at any depth, including the ends', () => {
    for (const t of [-1, 0, 0.5, 1, 2]) {
      const [r, g, b] = blend(RAMPS.idle, RAMPS.speaking, 0.3, t)
      for (const channel of [r, g, b]) {
        expect(Number.isFinite(channel)).toBe(true)
        expect(channel).toBeGreaterThanOrEqual(0)
        expect(channel).toBeLessThanOrEqual(255)
      }
    }
  })
})
