import { useState } from 'react'
import type { ComputerCommand, ComputerStatus } from '../../../shared/computer'

export function ComputerIsland({ status }: { status: ComputerStatus }): React.JSX.Element {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const control = async (command: ComputerCommand): Promise<void> => {
    setBusy(true)
    setError(false)
    try {
      await window.marvi.computerControl(command)
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }
  const paused = status.state === 'paused' || status.state === 'private'
  return (
    <div className="dynamic-island island-confirmation" role="status" aria-live="polite">
      <div className="confirmation-copy">
        <small>{status.state === 'private' ? 'PRIVATE INPUT' : 'COMPUTER USE'}</small>
        <strong>
          {error || status.state === 'unavailable'
            ? 'Computer controls unavailable. Retry.'
            : status.state === 'unknown'
              ? 'Computer action outcome unknown'
              : status.state === 'stopping'
                ? 'Marvi is stopping computer use'
                : paused
                  ? 'Computer use paused'
                  : 'Marvi is using the computer'}
        </strong>
      </div>
      <div className="confirmation-actions">
        <button
          disabled={busy || status.state === 'stopping'}
          onClick={() => {
            void control(paused ? 'resume' : 'private')
          }}
        >
          {paused ? 'RESUME' : 'PRIVATE INPUT'}
        </button>
        {!paused && (
          <button
            disabled={busy || status.state === 'stopping'}
            onClick={() => {
              void control('stop')
            }}
          >
            STOP
          </button>
        )}
      </div>
    </div>
  )
}
