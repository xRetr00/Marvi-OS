import { describe, expect, it } from 'vitest'
import { projectVoicePoint } from './projection'

describe('voice sphere perspective', () => {
  it('magnifies the near surface relative to the far surface', () => {
    const near = projectVoicePoint(0.5, 0, 0.8)
    const far = projectVoicePoint(0.5, 0, -0.8)
    expect(near.x).toBeGreaterThan(far.x)
    expect(near.perspective).toBeGreaterThan(far.perspective)
  })

  it('occludes rear-facing dots instead of drawing through the sphere', () => {
    expect(projectVoicePoint(0, 0, 1).visible).toBe(true)
    expect(projectVoicePoint(0, 0, -1).visible).toBe(false)
    expect(projectVoicePoint(1, 0, 0).visible).toBe(false)
  })

  it('lights the upper-left surface more than the lower-right surface', () => {
    expect(projectVoicePoint(-0.5, 0.5, 0.7).light).toBeGreaterThan(
      projectVoicePoint(0.5, -0.5, 0.7).light
    )
  })

  it('stays finite across the voice wave envelope', () => {
    for (const radius of [0.86, 1, 1.14]) {
      const point = projectVoicePoint(0.5 * radius, 0.5 * radius, 0.7 * radius)
      expect(Number.isFinite(point.x)).toBe(true)
      expect(point.light).toBeGreaterThanOrEqual(0.22)
      expect(point.light).toBeLessThanOrEqual(1)
    }
  })
})
