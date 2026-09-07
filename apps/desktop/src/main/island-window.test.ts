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
    ).toEqual({ x: 623, y: 50, width: 154, height: 34 })
  })

  it('leaves desktop space above the idle capsule', () => {
    expect(
      islandWindowBounds({ x: 100, y: 40, width: 1200, height: 800 }, ISLAND_SEED_CONTENT_SIZE)
    ).toEqual({ x: 654, y: 50, width: 92, height: 32 })
  })

  it('keeps compact activity detached at the same height', () => {
    expect(
      islandWindowBounds({ x: 100, y: 40, width: 1200, height: 800 }, { width: 104, height: 32 })
    ).toEqual({ x: 646, y: 50, width: 108, height: 36 })
  })

  it('preserves the gap on an offset display when expanded', () => {
    expect(
      islandWindowBounds({ x: -1920, y: -1080, width: 1920, height: 1080 }, ISLAND_MAX_CONTENT_SIZE)
    ).toEqual({ x: -1142, y: -1070, width: 364, height: 96 })
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
