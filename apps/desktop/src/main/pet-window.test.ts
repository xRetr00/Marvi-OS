import { describe, expect, it } from 'vitest'

import {
  DEFAULT_PET_PREFERENCES,
  normalizePetPreferences,
  petSpriteBounds,
  pointInBounds,
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
      y: 550,
      width: 192,
      height: 272
    })
  })

  it('supports a compact left-side companion', () => {
    expect(petWindowBounds(workArea, { side: 'left', scale: 0.5 })).toEqual({
      x: 118,
      y: 686,
      width: 96,
      height: 136
    })
  })
})

describe('native host geometry', () => {
  const host = { x: 10, y: 20, width: 96, height: 136 }

  it('keeps gaze geometry on the atlas sprite and reserves controls below it', () => {
    expect(petSpriteBounds(host)).toEqual({ x: 10, y: 20, width: 96, height: 104 })
  })

  it('includes the hover controls but excludes the outer edge', () => {
    expect(pointInBounds(host, { x: 58, y: 150 })).toBe(true)
    expect(pointInBounds(host, { x: 106, y: 150 })).toBe(false)
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
