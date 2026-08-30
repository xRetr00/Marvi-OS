import type { UsageCounters, UsageDay, UsageHour } from '../../../shared/runtime'

export type UsageRange = 'year' | 'month' | 'week' | 'day' | 'hours'

export interface UsageCell extends UsageCounters {
  key: string
  label: string
  level: number
  inRange: boolean
}

const EMPTY: UsageCounters = { input: 0, output: 0, cachedInput: 0, reasoning: 0, billable: 0 }
const DAY = 86_400_000
const HOUR = 3_600_000

function utcDay(value: Date): number {
  return Date.UTC(value.getUTCFullYear(), value.getUTCMonth(), value.getUTCDate())
}

function dayKey(value: number): string {
  return new Date(value).toISOString().slice(0, 10)
}

function hourKey(value: number): string {
  return new Date(value).toISOString().slice(0, 13) + ':00:00Z'
}

function levels<T extends { billable: number }>(rows: T[]): number[] {
  const positive = rows
    .map((row) => row.billable)
    .filter((value) => value > 0)
    .sort((a, b) => a - b)
  if (!positive.length) return rows.map(() => 0)
  const threshold = (part: number): number =>
    positive[Math.min(positive.length - 1, Math.floor((positive.length - 1) * part))]
  const cuts = [threshold(0.25), threshold(0.5), threshold(0.75)]
  return rows.map((row) => {
    if (row.billable <= 0) return 0
    if (row.billable <= cuts[0]) return 1
    if (row.billable <= cuts[1]) return 2
    if (row.billable <= cuts[2]) return 3
    return 4
  })
}

export function buildUsageCells(
  range: UsageRange,
  daily: UsageDay[],
  hourly: UsageHour[],
  current = new Date()
): UsageCell[] {
  const dayMap = new Map(daily.map((row) => [row.date, row]))
  const hourMap = new Map(hourly.map((row) => [row.hour, row]))
  const today = utcDay(current)
  let stamps: number[]
  let source: Map<string, UsageDay | UsageHour>
  let keyOf: (stamp: number) => string
  let labelOf: (stamp: number) => string
  let visibleStart = 0

  if (range === 'year' || range === 'month') {
    const start =
      range === 'year'
        ? today - 364 * DAY
        : Date.UTC(current.getUTCFullYear(), current.getUTCMonth(), 1)
    visibleStart = start
    const weekday = (new Date(start).getUTCDay() + 6) % 7
    const alignedStart = start - weekday * DAY
    stamps = Array.from(
      { length: Math.floor((today - alignedStart) / DAY) + 1 },
      (_, index) => alignedStart + index * DAY
    )
    source = dayMap
    keyOf = dayKey
    labelOf = (stamp) =>
      new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeZone: 'UTC' }).format(stamp)
  } else {
    const currentHour = Date.UTC(
      current.getUTCFullYear(),
      current.getUTCMonth(),
      current.getUTCDate(),
      current.getUTCHours()
    )
    const start =
      range === 'week' ? today - 6 * DAY : range === 'day' ? today : currentHour - 23 * HOUR
    const count = range === 'week' ? 7 * 24 : range === 'day' ? current.getUTCHours() + 1 : 24
    visibleStart = start
    stamps = Array.from({ length: count }, (_, index) => start + index * HOUR)
    source = hourMap
    keyOf = hourKey
    labelOf = (stamp) =>
      new Intl.DateTimeFormat('en', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hourCycle: 'h23',
        timeZone: 'UTC'
      }).format(stamp)
  }

  const rows = stamps.map((stamp) => {
    const key = keyOf(stamp)
    const inRange = stamp >= visibleStart
    return {
      key,
      label: labelOf(stamp),
      inRange,
      ...(inRange ? (source.get(key) ?? EMPTY) : EMPTY)
    }
  })
  const activity = levels(rows)
  return rows.map((row, index) => ({ ...row, level: activity[index] }))
}

export function usageMonthLabels(cells: UsageCell[]): Array<{ column: number; label: string }> {
  const labels: Array<{ column: number; label: string }> = []
  let last = ''
  cells.forEach((cell, index) => {
    if (!cell.inRange) return
    const value = new Date(`${cell.key}T00:00:00Z`)
    const month = value.toLocaleString('en', { month: 'short', timeZone: 'UTC' })
    if (month !== last) {
      const column = Math.floor(index / 7) + 1
      if (!labels.length || column - labels[labels.length - 1].column >= 3)
        labels.push({ column, label: month })
      last = month
    }
  })
  return labels
}
