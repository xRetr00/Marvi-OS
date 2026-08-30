import { describe, expect, it } from 'vitest'

import type { UsageDay, UsageHour } from '../../../shared/runtime'
import { buildUsageCells } from './usage-heatmap'

const counters = { input: 100, output: 20, cachedInput: 80, reasoning: 0, billable: 40 }

describe('usage heatmap ranges', () => {
  it('aligns a month to calendar weeks and keeps recorded daily activity', () => {
    const daily: UsageDay[] = [{ date: '2026-08-23', ...counters }]
    const cells = buildUsageCells('month', daily, [], new Date('2026-08-31T18:20:00Z'))
    expect(cells[0].key).toBe('2026-07-27')
    expect(cells.at(-1)?.key).toBe('2026-08-31')
    expect(cells.find((cell) => cell.key === '2026-08-23')?.billable).toBe(40)
  })

  it('uses persisted hourly buckets for day and rolling 24-hour views', () => {
    const hourly: UsageHour[] = [{ hour: '2026-08-31T18:00:00Z', ...counters }]
    const day = buildUsageCells('day', [], hourly, new Date('2026-08-31T18:20:00Z'))
    const rolling = buildUsageCells('hours', [], hourly, new Date('2026-08-31T18:20:00Z'))
    expect(day).toHaveLength(19)
    expect(day.at(-1)?.billable).toBe(40)
    expect(rolling).toHaveLength(24)
    expect(rolling.at(-1)?.key).toBe('2026-08-31T18:00:00Z')
  })

  it('uses distribution levels so one extreme bucket does not flatten every other cell', () => {
    const hourly: UsageHour[] = [1, 2, 3, 1000].map((billable, index) => ({
      hour: `2026-08-31T${String(15 + index).padStart(2, '0')}:00:00Z`,
      ...counters,
      billable
    }))
    const cells = buildUsageCells('day', [], hourly, new Date('2026-08-31T18:20:00Z'))
    expect(cells.slice(-4).map((cell) => cell.level)).toEqual([1, 2, 3, 4])
  })
})
