import { describe, expect, it } from 'vitest'
import { LocationHost, validFix } from './location'

describe('native location protocol', () => {
  it('refuses incomplete, non-finite and out-of-range fixes', () => {
    expect(validFix({ status: 'ready' })).toBe(false)
    const fix = { status: 'ready', latitude: 40, longitude: 31, accuracy_m: 1500, timestamp: 100 }
    expect(validFix(fix)).toBe(true)
    for (const update of [
      { latitude: 91 },
      { longitude: -181 },
      { latitude: NaN },
      { accuracy_m: -1 },
      { timestamp: 'now' }
    ]) {
      expect(validFix({ ...fix, ...update })).toBe(false)
    }
    expect(validFix({ status: 'denied' })).toBe(true)
    expect(validFix({ status: 'invented' })).toBe(false)
  })
  it('cancels an acquisition before the Gateway returns its settings', async () => {
    let finish!: (state: unknown) => void
    const response = new Promise<unknown>((resolve) => {
      finish = resolve
    })
    let calls = 0
    const host = new LocationHost(
      { isPackaged: false, getAppPath: () => '/nonexistent' },
      async () => {
        calls++
        return response
      }
    )
    const reading = host.refresh(false)
    const cancelled = host.cancelRead()
    finish({ settings: { mode: 'automatic' }, generation: 1, place: null })
    await Promise.all([reading, cancelled])
    expect(calls).toBe(1) // No helper result/fix POST after cancellation.
    host.stop()
  })
})
