/**
 * Haptic patterns for the control center (adapted from the the predecessor assistant
 * desktop shell, MIT). Web haptics are audio-transducer ticks, so they work
 * on speakers/headphones as subtle UI feedback. Keep the vocabulary tiny and
 * consistent: tap, selection, open, close, success, error, warning.
 *
 * Provenance: the predecessor desktop's haptics module +
 * components/haptics-provider.tsx (see docs/UPSTREAM.md).
 */
import type { HapticInput, TriggerOptions, WebHapticsOptions } from 'web-haptics'

export type HapticIntent = 'tap' | 'selection' | 'open' | 'close' | 'success' | 'error' | 'warning'

interface HapticConfig {
  options?: TriggerOptions
  pattern: HapticInput
}

const PATTERNS: Record<HapticIntent, HapticConfig> = {
  tap: { pattern: [{ duration: 12, intensity: 0.55 }] },
  selection: { pattern: [{ duration: 8, intensity: 0.4 }] },
  open: { pattern: [{ duration: 18, intensity: 0.6 }] },
  close: { pattern: [{ duration: 14, intensity: 0.45 }] },
  success: {
    pattern: [
      { duration: 24, intensity: 0.5 },
      { delay: 40, duration: 26, intensity: 0.66 }
    ]
  },
  error: {
    pattern: [
      { duration: 30, intensity: 0.85 },
      { delay: 50, duration: 42, intensity: 0.7 }
    ]
  },
  warning: { pattern: [{ duration: 34, intensity: 0.62 }] }
}

/** Electron on Windows has no Vibration API. The upstream library's debug
 * path is its documented audio-transducer fallback for desktop feedback. */
export const DESKTOP_HAPTICS_OPTIONS: WebHapticsOptions = {
  debug: true,
  showSwitch: false
}

type TriggerFn = (pattern: HapticInput, options?: TriggerOptions) => Promise<void> | undefined

let trigger: TriggerFn | null = null
const HAPTICS_MUTED_KEY = 'marvi:haptics-muted'
let muted = readMutedPreference()

function readMutedPreference(): boolean {
  try {
    return typeof window !== 'undefined' && window.localStorage.getItem(HAPTICS_MUTED_KEY) === 'true'
  } catch {
    return false
  }
}

export function getHapticsMuted(): boolean {
  return muted
}

export function setHapticsMuted(next: boolean): void {
  muted = next
  try {
    if (typeof window !== 'undefined') window.localStorage.setItem(HAPTICS_MUTED_KEY, String(next))
  } catch {
    // Preference persistence is optional; the current session still updates.
  }
}

export function registerHapticTrigger(next: TriggerFn | null): void {
  trigger = next
}

export function haptic(intent: HapticIntent): void {
  if (muted || !trigger) return
  const config = PATTERNS[intent]
  try {
    void Promise.resolve(trigger(config.pattern, config.options)).catch(() => undefined)
  } catch {
    // Audio device vanished mid-gesture — never let feedback break UI actions.
  }
}
