import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  DESKTOP_HAPTICS_OPTIONS,
  getHapticsMuted,
  haptic,
  registerHapticTrigger,
  setHapticsMuted
} from './haptics'

afterEach(() => {
  registerHapticTrigger(null)
  setHapticsMuted(false)
})

describe('desktop haptics', () => {
  it('enables the upstream audio-transducer path used by Electron', () => {
    expect(DESKTOP_HAPTICS_OPTIONS).toEqual({ debug: true, showSwitch: false })
  })

  it('forwards the selected feedback pattern', () => {
    const trigger = vi.fn(() => Promise.resolve())
    registerHapticTrigger(trigger)

    haptic('selection')

    expect(trigger).toHaveBeenCalledWith([{ duration: 8, intensity: 0.4 }], undefined)
  })

  it('does not throw when the audio path rejects', async () => {
    registerHapticTrigger(() => Promise.reject(new Error('audio device vanished')))

    expect(() => haptic('tap')).not.toThrow()
    await Promise.resolve()
  })

  it('suppresses every feedback pattern while muted', () => {
    const trigger = vi.fn(() => Promise.resolve())
    registerHapticTrigger(trigger)
    setHapticsMuted(true)

    haptic('warning')

    expect(getHapticsMuted()).toBe(true)
    expect(trigger).not.toHaveBeenCalled()
  })
})
