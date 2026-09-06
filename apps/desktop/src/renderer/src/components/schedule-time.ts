/**
 * Turning a schedule into words and a countdown.
 *
 * Separate from the card that draws them because a file that exports both a
 * component and a helper loses Fast Refresh, and because these two have real
 * logic in them and are worth testing on their own.
 */
import type { ScheduleRow } from '../../../shared/runtime'

/** The handful of crontabs worth naming.
 *
 *  Anything not in here keeps its expression, which is the honest answer:
 *  inventing English for `7 3-5 1,15 * 2` would be worse than showing the
 *  person the thing they typed.
 */
const KNOWN_CRONTABS: Record<string, string> = {
  '* * * * *': 'every minute',
  '*/5 * * * *': 'every five minutes',
  '0 * * * *': 'hourly, on the hour',
  '0 0 * * *': 'daily at midnight',
  '0 9 * * *': 'daily at 09:00',
  '0 6 * * 1-5': 'weekday mornings at 06:00',
  '0 0 * * 0': 'weekly on Sunday'
}

/** `0 6 * * 1-5` is not a sentence. This is the closest short one. */
export function saysWhen(row: Pick<ScheduleRow, 'kind' | 'expression'>): string {
  if (row.kind === 'interval') {
    const minutes = Number(row.expression)
    if (!Number.isFinite(minutes)) return `every ${row.expression} minutes`
    if (minutes % 60 === 0 && minutes >= 60) {
      const hours = minutes / 60
      return hours === 1 ? 'hourly' : `every ${hours} hours`
    }
    return `every ${minutes} minutes`
  }
  if (row.kind === 'once') return `once, at ${row.expression.slice(0, 16).replace('T', ' ')}`
  return KNOWN_CRONTABS[row.expression.trim()] ?? row.expression
}

/**
 * "in 4m", "in 2d", or "due" -- never a bare ISO stamp.
 *
 * `now` is injectable so the thresholds can be tested without waiting for
 * real time to pass.
 */
export function untilNext(next: string | null, now: number = Date.now()): string {
  if (!next) return ''
  const at = new Date(next).getTime()
  if (Number.isNaN(at)) return ''
  const seconds = Math.round((at - now) / 1000)
  if (seconds <= 0) return 'due'
  if (seconds < 90) return `in ${seconds}s`
  if (seconds < 5400) return `in ${Math.round(seconds / 60)}m`
  if (seconds < 172800) return `in ${Math.round(seconds / 3600)}h`
  return `in ${Math.round(seconds / 86400)}d`
}
