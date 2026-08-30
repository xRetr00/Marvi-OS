import { describe, expect, it } from 'vitest'

import { activitySeconds, formatActivityTime } from '../activity-time'

describe('chat activity timing', () => {
  it('measures from the turn timestamp without going negative', () => {
    expect(
      activitySeconds('2026-08-30T00:00:00.000Z', Date.parse('2026-08-30T00:00:08.900Z'))
    ).toBe(8)
    expect(
      activitySeconds('2026-08-30T00:00:10.000Z', Date.parse('2026-08-30T00:00:08.000Z'))
    ).toBe(0)
  })

  it('uses compact seconds and minute notation', () => {
    expect(formatActivityTime(9)).toBe('9s')
    expect(formatActivityTime(65)).toBe('1:05')
  })
})
