import { describe, expect, it } from 'vitest'
import { DEFAULT_SUMMON_HOTKEY, summonAccelerator } from './summon'

describe('summon hotkey', () => {
  it('defaults on, takes a custom accelerator, and can be switched off', () => {
    expect(summonAccelerator({})).toBe(DEFAULT_SUMMON_HOTKEY)
    expect(summonAccelerator({ MARVI_SUMMON_HOTKEY: ' Control+Space ' })).toBe('Control+Space')
    for (const off of ['off', 'OFF', '', 'none', '0', 'false']) {
      expect(summonAccelerator({ MARVI_SUMMON_HOTKEY: off })).toBeNull()
    }
  })
})
