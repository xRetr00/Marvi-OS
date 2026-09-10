/**
 * Turning recorded wake detections into something readable.
 *
 * Separate from the component so it can be tested without a DOM, and because
 * a file that exports both a component and helpers breaks fast refresh --
 * `model-picker-utils.ts` is split for the same reason.
 */
import type { StreamEntry } from './ui/data-stream'

/** The floor and ceiling the listener itself accepts.
 *
 * `threshold()` in the wake host filters to `> 0.0 && <= 1.0` and silently
 * falls back to the default outside that, so a value saved outside the range
 * would appear to work and quietly do nothing. */
export const LOWEST = 0.01
export const HIGHEST = 1

/** Three decimals, because the interesting differences are in the third:
 * 0.475 and 0.477 were two separate false alarms. */
export function readable(value: number): string {
  return value.toFixed(3)
}

export function usableThreshold(typed: string): number | null {
  const parsed = Number(typed)
  if (!typed.trim() || !Number.isFinite(parsed)) return null
  return parsed >= LOWEST && parsed <= HIGHEST ? parsed : null
}

/** The detections as stream entries, oldest first so the log reads downwards.
 *
 * Marked by whether each one cleared the line currently set, which is the
 * only honest reading: nothing in the model says a fire at 0.2 means less
 * than one at 0.9 in a calibrated way. */
export function asEntries(
  recent: { at: number; confidence: number }[],
  threshold: number
): StreamEntry[] {
  return [...recent]
    .sort((a, b) => a.at - b.at)
    .map((one) => {
      const woke = one.confidence >= threshold
      return {
        timestamp: new Date(one.at * 1000).toLocaleTimeString(),
        text: woke ? 'woke her' : 'below the line',
        tone: woke ? ('warning' as const) : ('info' as const),
        hint: readable(one.confidence)
      }
    })
}

/** The loudest thing that fired, or 0 when nothing has. */
export function loudest(recent: { confidence: number }[]): number {
  return recent.reduce((most, one) => Math.max(most, one.confidence), 0)
}
