import { describe, expect, it } from 'vitest'

import {
  ISLAND_MAX_CONTENT_SIZE,
  ISLAND_MIN_CONTENT_SIZE,
  ISLAND_SEED_CONTENT_SIZE,
  islandWindowBounds,
  normalizeIslandContentSize,
  normalizeIslandInteractionMode
} from './island-window'

describe('normalizeIslandContentSize', () => {
  it('rejects malformed renderer payloads', () => {
    expect(normalizeIslandContentSize(null)).toBeNull()
    expect(normalizeIslandContentSize({ width: 'wide', height: 40 })).toBeNull()
  })

  it('rounds and clamps renderer measurements', () => {
    expect(normalizeIslandContentSize({ width: 149.6, height: 30.4 })).toEqual({
      width: 150,
      height: 30
    })
    expect(normalizeIslandContentSize({ width: 1, height: 999 })).toEqual({
      width: ISLAND_MIN_CONTENT_SIZE.width,
      height: ISLAND_MAX_CONTENT_SIZE.height
    })
  })
})

describe('islandWindowBounds', () => {
  it('centers the tightly fitted transparent host around the measured content', () => {
    expect(
      islandWindowBounds({ x: 100, y: 40, width: 1200, height: 800 }, { width: 150, height: 30 })
    ).toEqual({ x: 623, y: 40, width: 154, height: 34 })
  })

  it('anchors the recessed seed directly to the work-area edge', () => {
    expect(
      islandWindowBounds({ x: 100, y: 40, width: 1200, height: 800 }, ISLAND_SEED_CONTENT_SIZE)
    ).toEqual({ x: 660, y: 40, width: 80, height: 12 })
  })

  it('keeps compact orb states attached to the same top edge', () => {
    expect(
      islandWindowBounds({ x: 100, y: 40, width: 1200, height: 800 }, { width: 38, height: 30 })
    ).toEqual({ x: 679, y: 40, width: 42, height: 34 })
  })

  it('supports explicit left and right placement', () => {
    const workArea = { x: 100, y: 40, width: 1200, height: 800 }
    const size = { width: 150, height: 30 }
    expect(islandWindowBounds(workArea, size, 'left').x).toBe(118)
    expect(islandWindowBounds(workArea, size, 'right').x).toBe(1128)
  })
})

describe('normalizeIslandInteractionMode', () => {
  it('allows pointer hover without granting focus and rejects malformed modes', () => {
    expect(normalizeIslandInteractionMode('hover')).toBe('hover')
    expect(normalizeIslandInteractionMode('interactive')).toBe('interactive')
    expect(normalizeIslandInteractionMode(true)).toBe('passive')
  })
})
