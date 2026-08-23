import { describe, expect, it } from 'vitest'

import {
  DEFAULT_PET_PREFERENCES,
  normalizePetPreferences,
  petLookDirection,
  petWindowBounds
} from './pet-window'

describe('normalizePetPreferences', () => {
  it('uses safe defaults for malformed values', () => {
    expect(normalizePetPreferences(null)).toEqual(DEFAULT_PET_PREFERENCES)
    expect(normalizePetPreferences({ enabled: 'yes', side: 'middle', scale: 4 })).toEqual(
      DEFAULT_PET_PREFERENCES
    )
  })

  it('accepts supported placement values', () => {
    expect(
      normalizePetPreferences({ enabled: false, displayId: 7, side: 'left', scale: 0.5 })
    ).toEqual({ enabled: false, displayId: 7, side: 'left', scale: 0.5 })
  })
})

describe('petWindowBounds', () => {
  const workArea = { x: 100, y: 40, width: 1200, height: 800 }

  it('anchors at the bottom right inside the work area', () => {
    expect(petWindowBounds(workArea, { side: 'right', scale: 1 })).toEqual({
      x: 1090,
      y: 614,
      width: 192,
      height: 208
    })
  })

  it('supports a compact left-side companion', () => {
    expect(petWindowBounds(workArea, { side: 'left', scale: 0.5 })).toEqual({
      x: 118,
      y: 718,
      width: 96,
      height: 104
    })
  })
})

describe('petLookDirection', () => {
  const bounds = { x: 100, y: 100, width: 192, height: 208 }
  const focus = { x: 196, y: 179.04 }

  it('returns the cardinal atlas directions', () => {
    expect(petLookDirection(bounds, { x: focus.x, y: focus.y - 100 })).toBe(0)
    expect(petLookDirection(bounds, { x: focus.x + 100, y: focus.y })).toBe(4)
    expect(petLookDirection(bounds, { x: focus.x, y: focus.y + 100 })).toBe(8)
    expect(petLookDirection(bounds, { x: focus.x - 100, y: focus.y })).toBe(12)
  })

  it('returns null inside the centered dead zone', () => {
    expect(petLookDirection(bounds, focus)).toBeNull()
  })
})
