import { afterEach, describe, expect, it, vi } from 'vitest'

import { DESKTOP_HAPTICS_OPTIONS, haptic, registerHapticTrigger } from './haptics'

afterEach(() => registerHapticTrigger(null))

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
})
