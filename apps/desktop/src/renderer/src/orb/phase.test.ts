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
      expect(PHASE_ACCENT[phase]).toMatch(/^var\(--ui-/)
    }
    expect(accentFor('error')).toBe('var(--ui-danger)')
  })
})
