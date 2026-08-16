/**
 * Haptic patterns for the control center (adapted from the the predecessor assistant
 * desktop shell, MIT). Web haptics are audio-transducer ticks, so they work
 * on speakers/headphones as subtle UI feedback. Keep the vocabulary tiny and
 * consistent: tap, selection, open, close, success, error, warning.
 *
 * Provenance: the predecessor desktop's haptics module +
 * components/haptics-provider.tsx (see docs/UPSTREAM.md).
 */
import type { HapticInput, TriggerOptions } from 'web-haptics'

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

type TriggerFn = (pattern: HapticInput, options?: TriggerOptions) => void

let trigger: TriggerFn | null = null

export function registerHapticTrigger(next: TriggerFn | null): void {
  trigger = next
}

export function haptic(intent: HapticIntent): void {
  if (!trigger) return
  const config = PATTERNS[intent]
  try {
    trigger(config.pattern, config.options)
  } catch {
    // Audio device vanished mid-gesture — never let feedback break UI actions.
  }
}
