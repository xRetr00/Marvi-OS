/**
 * Recovery surface for a hard boot failure (gateway never came up). Without
 * this the shell renders dead — "gateway offline" with no way to retry or
 * see diagnostics. Adapted from the the predecessor assistant desktop BootFailureOverlay
 * (MIT), trimmed to the Marvi OS local contract: retry the gateway poll and
 * reveal diagnostics; no remote reauth path exists here.
 * Provenance: the predecessor assistant\apps\desktop\src\components\boot-failure-overlay.tsx
 * (see docs/UPSTREAM.md).
 */
import { useStore } from '@nanostores/react'

import { useEffect, useState } from 'react'

import { $runtimeState } from '../store/voice-state'
import { haptic } from '../lib/haptics'

export function BootFailureOverlay(): React.JSX.Element | null {
  const runtime = useStore($runtimeState)

  const [staleFor, setStaleFor] = useState(0)

  useEffect(() => {
    if (runtime.state !== 'offline' && runtime.state !== 'starting') {
      // Reset on the next tick rather than during render-phase effects.
      const reset = window.setTimeout(() => setStaleFor(0), 0)
      return () => window.clearTimeout(reset)
    }
    // A Gateway that never arrives must surface as a failure the user can act
    // on, not an animation that runs forever.
    const timer = window.setInterval(() => setStaleFor((n) => n + 1), 1_000)
    return () => window.clearInterval(timer)
  }, [runtime.state])

  const neverCameUp = staleFor >= 30
  if (runtime.state !== 'error' && !neverCameUp) return null

  const details = Object.entries(runtime.components).map(
    ([name, component]) =>
      `${name.toUpperCase()}: ${component.state.toUpperCase()} / ${component.detail}`
  )

  return (
    <div className="boot-failure-overlay" role="alert">
      <div className="boot-failure-card">
        <span className="panel-label">{'// BOOT FAILURE'}</span>
        <h2>MARVI GATEWAY DID NOT START</h2>
        <p>
          The local gateway never became ready. Marvi OS keeps the shell alive so you can retry or
          inspect diagnostics instead of staring at a dead window.
        </p>
        <pre className="boot-failure-log">{details.join('\n')}</pre>
        <div className="boot-failure-actions">
          <button
            onClick={() => {
              haptic('tap')
              // Restart the Gateway, not the window. This reloaded the
              // renderer, which the Gateway neither knows nor cares about, so
              // the overlay came straight back and the button looked broken.
              void window.marvi?.retryService('gateway')
            }}
            type="button"
          >
            RETRY BOOT
          </button>
          <button
            onClick={() => {
              haptic('tap')
              // Reachable from here on purpose: a Gateway that will not start
              // is exactly when an update is most likely to be the fix, and it
              // was previously only offered from a page behind this overlay.
              void window.marvi?.startUpdate()
            }}
            type="button"
          >
            UPDATE MARVI
          </button>
          <button
            onClick={() => {
              haptic('tap')
              window.marvi?.showMain()
            }}
            type="button"
          >
            OPEN TRAY SHELL
          </button>
        </div>
        <small>GATEWAY LOGS: %LOCALAPPDATA%\Marvi-OS\logs</small>
      </div>
    </div>
  )
}
