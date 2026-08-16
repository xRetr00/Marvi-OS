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

import { $runtimeState } from '../store/voice-state'
import { haptic } from '../lib/haptics'

export function BootFailureOverlay(): React.JSX.Element | null {
  const runtime = useStore($runtimeState)

  if (runtime.state !== 'error') return null

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
              window.location.reload()
            }}
            type="button"
          >
            RETRY BOOT
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
