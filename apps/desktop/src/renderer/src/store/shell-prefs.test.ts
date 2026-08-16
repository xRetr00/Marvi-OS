import { afterEach, describe, expect, it } from 'vitest'

import {
  $backgroundMode,
  $backgroundOpacity,
  setBackgroundMode,
  setBackgroundOpacity
} from './background'
import { $translucency, setTranslucency } from './translucency'

afterEach(() => {
  $backgroundMode.set('electricGaze')
  $backgroundOpacity.set(42)
  $translucency.set(0)
})

describe('background store', () => {
  it('defaults to the local Electric Gaze backdrop', () => {
    expect($backgroundMode.get()).toBe('electricGaze')
  })

  it('accepts only known backdrop ids through the setter', () => {
    setBackgroundMode('none')
    expect($backgroundMode.get()).toBe('none')
  })

  it('clamps backdrop opacity into 0–100', () => {
    setBackgroundOpacity(140)
    expect($backgroundOpacity.get()).toBe(100)
    setBackgroundOpacity(-20)
    expect($backgroundOpacity.get()).toBe(0)
  })
})

describe('translucency store', () => {
  it('defaults to fully opaque', () => {
    expect($translucency.get()).toBe(0)
  })

  it('clamps the lever into 0–100', () => {
    setTranslucency(120)
    expect($translucency.get()).toBe(100)
    setTranslucency(-4)
    expect($translucency.get()).toBe(0)
    setTranslucency(37.4)
    expect($translucency.get()).toBe(37)
  })
})
