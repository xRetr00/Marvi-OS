import { describe, expect, it } from 'vitest'

import {
  ISLAND_MAX_CONTENT_SIZE,
  ISLAND_MIN_CONTENT_SIZE,
  islandWindowBounds,
  normalizeIslandContentSize
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
  it('centers the transparent host around only the measured content', () => {
    expect(
      islandWindowBounds({ x: 100, y: 40, width: 1200, height: 800 }, { width: 150, height: 30 })
    ).toEqual({ x: 613, y: 46, width: 174, height: 54 })
  })
})
