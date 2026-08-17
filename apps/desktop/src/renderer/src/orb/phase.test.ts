import { describe, expect, it } from 'vitest'

import { ASSISTANT_PHASES } from '../../../shared/runtime'
import { PHASE_ACCENT, PHASE_ORB, accentFor, orbStateFor } from './phase'

describe('phase → orb mapping', () => {
  it('maps every assistant phase to a distinct orb state', () => {
    for (const phase of ASSISTANT_PHASES) {
      expect(PHASE_ORB[phase]).toBeTruthy()
    }
    expect(orbStateFor('listening')).toBe('listening')
    expect(orbStateFor('thinking')).toBe('searching')
    expect(orbStateFor('ready')).toBe('breathing')
  })

  it('maps every assistant phase to an accent color', () => {
    for (const phase of ASSISTANT_PHASES) {
      expect(PHASE_ACCENT[phase]).toMatch(/^#[0-9a-f]{6}$/i)
    }
    expect(accentFor('error')).toBe('#f87171')
  })
})
