import { useEffect, useState } from 'react'
import type { BrowserCommand, BrowserSession } from '../../../shared/browser'

export function useBrowserHandoff(): BrowserSession | null {
  const [session, setSession] = useState<BrowserSession | null>(null)
  useEffect(() => {
    let alive = true
    const refresh = async (): Promise<void> => {
      try {
        const status = await window.marvi?.getBrowser()
        if (alive)
          setSession(
            status?.sessions.find((s) => s.state === 'private') ??
              status?.sessions.find((s) =>
                ['running', 'starting', 'stopping', 'resuming'].includes(s.state)
              ) ??
              null
          )
      } catch {
        if (alive) setSession(null)
      }
    }
    void refresh()
    const timer = setInterval(() => {
      void refresh()
    }, 1500)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [])
  return session
}

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
            RESUME
          </button>
        ) : (
          <button
            disabled={busy || session.state === 'starting' || session.state === 'stopping'}
            onClick={() => {
              void control('private')
            }}
          >
            PRIVATE INPUT
          </button>
        )}
        <button
          disabled={busy || session.state === 'stopping'}
          onClick={() => {
            void control('stop')
          }}
        >
          STOP
        </button>
      </div>
    </div>
  )
}
