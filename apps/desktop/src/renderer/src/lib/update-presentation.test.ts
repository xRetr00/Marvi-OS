import { describe, expect, it } from 'vitest'

import { resolveVersionPresentation } from './update-presentation'

const update = {
  channel: 'dev' as const,
  available: true,
  upToDate: false,
  behindBy: 4,
  commits: [],
  targetRef: 'origin/main'
}

describe('desktop version presentation', () => {
  it('puts the available change count directly in the status bar label', () => {
    const result = resolveVersionPresentation({
      version: '0.5.0', check: update, loading: false, inProgress: false, handoff: 'idle'
    })
    expect(result.label).toBe('v0.5.0 (+4)')
    expect(result.tone).toBe('available')
  })

  it('makes update handoff and failure visible', () => {
    expect(resolveVersionPresentation({
      version: '0.5.0', check: update, loading: false, inProgress: false, handoff: 'starting'
    }).label).toContain('updating')
    expect(resolveVersionPresentation({
      version: '0.5.0', check: update, loading: false, inProgress: false, handoff: 'failed'
    }).tone).toBe('error')
  })
})
