import { Tr } from '../store/locale'
import { useState } from 'react'
import type { BrowserCommand, BrowserSession } from '../../../shared/browser'

export function BrowserIsland({ session }: { session: BrowserSession }): React.JSX.Element {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const control = async (command: BrowserCommand): Promise<void> => {
    setBusy(true)
    setError(false)
    try {
      await window.marvi.browserControl(session.id, session.revision, command)
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="dynamic-island island-confirmation" role="status" aria-live="polite">
      <div className="confirmation-copy">
        <small>{session.state === 'private' ? 'PRIVATE INPUT · PAUSED' : 'BROWSER'}</small>
        <strong>
          {error
            ? 'State changed. Retry or open Browser controls.'
            : session.state === 'private'
              ? 'Sign in on the website, then Resume.'
              : session.detail}
        </strong>
      </div>
      <div className="confirmation-actions">
        {session.state === 'private' ? (
          <button
            disabled={busy}
            onClick={() => {
              void control('resume')
            }}
          >
            <Tr text={'RESUME'} />
          </button>
        ) : (
          <button
            disabled={busy || session.state === 'starting' || session.state === 'stopping'}
            onClick={() => {
              void control('private')
            }}
          >
            <Tr text={'PRIVATE INPUT'} />
          </button>
        )}
        <button
          disabled={busy || session.state === 'stopping'}
          onClick={() => {
            void control('stop')
          }}
        >
          <Tr text={'STOP'} />
        </button>
      </div>
    </div>
  )
}
