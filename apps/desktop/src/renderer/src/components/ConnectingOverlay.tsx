/**
 * Full-screen connecting overlay shown while the Marvi Gateway / LiveKit
 * voice room boots. Adapted from the Marvi/Hermes desktop
 * GatewayConnectingOverlay (MIT): scramble-decode CONNECTING text plus a
 * glyph spinner, reduced-motion aware, exits once the gateway is ready.
 * Provenance: D:\hermes-agent\apps\desktop\src\components\gateway-connecting-overlay.tsx
 * (see docs/UPSTREAM.md).
 *
 * Marvi OS difference: the overlay tracks the gateway runtime state instead
 * of a websocket store — it stays up until the gateway reports ready (or an
 * error hands off to BootFailureOverlay), and it only covers the initial
 * boot; later flaps surface via the status bar, not a modal wall.
 */
import { useStore } from '@nanostores/react'
import { useEffect, useState } from 'react'

import { $runtimeState } from '../store/voice-state'
import { DecodeText } from './ui/decode-text'
import { GlyphSpinner } from './ui/glyph-spinner'

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
  )
}

export function ConnectingOverlay(): React.JSX.Element | null {
  const runtime = useStore($runtimeState)
  const [phase, setPhase] = useState<'live' | 'out' | 'gone'>('live')
  const [coldBootDone, setColdBootDone] = useState(false)

  const connecting = !coldBootDone && runtime.state !== 'ready' && runtime.state !== 'error'

  useEffect(() => {
    if (coldBootDone || phase !== 'live') return undefined
    if (connecting) return undefined
    // Connected (or failed) — run the exit choreography once.
    const timer = window.setTimeout(
      () => {
        setPhase('out')
        setColdBootDone(true)
        window.setTimeout(() => setPhase('gone'), prefersReducedMotion() ? 0 : 480)
      },
      prefersReducedMotion() ? 0 : 240
    )
    return () => window.clearTimeout(timer)
  }, [coldBootDone, connecting, phase])

  if (phase === 'gone') return null

  return (
    <div
      aria-hidden={!connecting}
      className={`connecting-overlay${phase === 'out' ? ' connecting-overlay-out' : ''}`}
      role="status"
    >
      <div className="connecting-block">
        <GlyphSpinner className="connecting-spinner" spinner="orbit" />
        <DecodeText active={connecting} className="connecting-text" prefix={4} text="CONNECTING" />
        <span className="connecting-detail">
          {runtime.components.gateway?.detail.toUpperCase() ?? 'Marvi Gateway offline'}
        </span>
      </div>
    </div>
  )
}
