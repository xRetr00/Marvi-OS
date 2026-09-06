import { describe, expect, it } from 'vitest'

import { saysWhen, untilNext } from './schedule-time'

describe('saysWhen', () => {
  it('names the crontabs a person would recognise', () => {
    expect(saysWhen({ kind: 'cron', expression: '0 6 * * 1-5' })).toBe('weekday mornings at 06:00')
    expect(saysWhen({ kind: 'cron', expression: '* * * * *' })).toBe('every minute')
  })

  it('leaves an expression it cannot name alone', () => {
    // Inventing English for this would be worse than showing what was typed.
    expect(saysWhen({ kind: 'cron', expression: '*/7 3-5 * * 2' })).toBe('*/7 3-5 * * 2')
  })

  it('reads intervals in whole hours where it can', () => {
    expect(saysWhen({ kind: 'interval', expression: '60' })).toBe('hourly')
    expect(saysWhen({ kind: 'interval', expression: '120' })).toBe('every 2 hours')
    expect(saysWhen({ kind: 'interval', expression: '30' })).toBe('every 30 minutes')
  })
})

describe('untilNext', () => {
  const now = Date.parse('2026-09-06T12:00:00Z')

  it('is empty when nothing is scheduled', () => {
    // Every repeating job had a null `next_run` until the Gateway learned to
    // compute one, so this is the case the page lived in.
    expect(untilNext(null, now)).toBe('')
  })

  it('counts down in a unit that suits the gap', () => {
    expect(untilNext('2026-09-06T12:00:45Z', now)).toBe('in 45s')
    expect(untilNext('2026-09-06T12:30:00Z', now)).toBe('in 30m')
    expect(untilNext('2026-09-06T20:00:00Z', now)).toBe('in 8h')
    expect(untilNext('2026-09-09T12:00:00Z', now)).toBe('in 3d')
  })

  it('says due rather than a negative countdown', () => {
    expect(untilNext('2026-09-06T11:59:00Z', now)).toBe('due')
  })
})
