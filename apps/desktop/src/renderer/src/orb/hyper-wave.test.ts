import { describe, expect, it } from 'vitest'
import { hyperWavePoint } from './hyper-wave'

describe('four-coordinate dotted orb', () => {
  it('changes the surface geometry with both time and voice', () => {
    const p = [0.6, 0.8, 0] as const
    expect(hyperWavePoint(p, 0, 0)).not.toEqual(hyperWavePoint(p, 2, 0))
    expect(hyperWavePoint(p, 2, 0)).not.toEqual(hyperWavePoint(p, 2, 1))
  })
  it('preserves a bounded orb over the full voice range', () => {
    for (let t = 0; t < 30; t += 0.5) {
      for (const energy of [0, 0.5, 1]) {
        for (let i = 0; i < 100; i++) {
          const y = 1 - (2 * (i + 0.5)) / 100
          const r = Math.sqrt(1 - y * y)
          const p = hyperWavePoint([r * Math.cos(i), y, r * Math.sin(i)], t, energy)
          expect(Math.hypot(...p)).toBeLessThan(1.9)
          expect(Math.hypot(...p)).toBeGreaterThan(0.35)
        }
      }
    }
  })
  it('has no longitude seam and keeps neighboring dots coherent', () => {
    const a = hyperWavePoint([-1, 0, 0.00001], 2, 1)
    const b = hyperWavePoint([-1, 0, -0.00001], 2, 1)
    expect(Math.hypot(...a.map((v, i) => v - b[i]))).toBeLessThan(0.001)
  })
  it('clamps audio and produces a deterministic still frame', () => {
    const p = [1, 0, 0] as const
    expect(hyperWavePoint(p, 0, 4)).toEqual(hyperWavePoint(p, 0, 1))
    expect(hyperWavePoint(p, 0, NaN)).toEqual(hyperWavePoint(p, 0, 0))
  })
})
