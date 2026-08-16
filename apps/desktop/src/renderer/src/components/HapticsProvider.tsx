/**
 * Haptics provider — registers web-haptics audio-transducer feedback for UI
 * gestures, adapted from the Marvi/Hermes desktop shell (MIT):
 * D:\hermes-agent\apps\desktop\src\components\haptics-provider.tsx.
 *
 * Keeps the Hermes warm-up trick: web-haptics builds its AudioContext lazily
 * inside the first trigger(), and the first AudioContext pays the audio
 * service spin-up (~hundreds of ms). Open/close a throwaway context at idle
 * so the first real haptic lands on an already-warm audio service.
 */
import { useEffect, type ReactNode } from 'react'
import { useWebHaptics } from 'web-haptics/react'

import { registerHapticTrigger } from '../lib/haptics'

export function HapticsProvider({ children }: { children: ReactNode }): React.JSX.Element {
  const { trigger } = useWebHaptics({ debug: false, showSwitch: false })

  useEffect(() => {
    registerHapticTrigger(trigger)
    return () => registerHapticTrigger(null)
  }, [trigger])

  useEffect(() => {
    if (typeof requestIdleCallback !== 'function' || typeof AudioContext === 'undefined') {
      return undefined
    }

    const id = requestIdleCallback(
      () => {
        try {
          void new AudioContext().close().catch(() => undefined)
        } catch {
          // No audio device (headless CI) — nothing to warm.
        }
      },
      { timeout: 2000 }
    )

    return () => cancelIdleCallback(id)
  }, [])

  return <>{children}</>
}
