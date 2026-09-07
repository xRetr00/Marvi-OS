import { describe, expect, it } from 'vitest'

import type { ScheduleRow } from '../../../shared/runtime'
import { editableWhen, SCHEDULE_TEMPLATES } from './schedule-templates'

describe('cron job templates', () => {
  it('provide editable action and agent starting points', () => {
    expect(SCHEDULE_TEMPLATES.some((template) => template.schedule.mode === 'action')).toBe(true)
    expect(SCHEDULE_TEMPLATES.some((template) => template.schedule.mode === 'agent')).toBe(true)
    expect(
      SCHEDULE_TEMPLATES.every((template) => template.schedule.name && template.schedule.when)
    ).toBe(true)
  })

  it('turns stored intervals back into parser input for editing', () => {
    expect(editableWhen({ kind: 'interval', expression: '120' } as ScheduleRow)).toBe(
      'every 120 minutes'
    )
    expect(editableWhen({ kind: 'cron', expression: '0 8 * * 1-5' } as ScheduleRow)).toBe(
      '0 8 * * 1-5'
    )
  })
})
