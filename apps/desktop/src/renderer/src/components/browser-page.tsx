import { useCallback, useEffect, useRef, useState } from 'react'
import type { BrowserCommand, BrowserSession, BrowserStatus } from '../../../shared/browser'
import { ControlPage, ControlSection } from './control-surface'
import './browser-page.css'

function BrowserViewport({ session }: { session: BrowserSession }): React.JSX.Element {
  const area = useRef<HTMLDivElement>(null)
  const [tab, setTab] = useState('')
  const lastTarget = useRef<string | undefined>(undefined)
  const target = session.tabs.find(t => t.id === tab)?.target ?? session.tabs[0]?.target
  if (target) lastTarget.current = target
  useEffect(() => {
    const place = (): void => {
      if (!area.current) return
      const rect = area.current.getBoundingClientRect()
      const y = Math.max(80, rect.top)
      const height = Math.min(innerHeight - 30, rect.bottom) - y
      void window.marvi.placeBrowser(height > 0 && rect.width > 0 ? {
        id: session.id, target: lastTarget.current,
        bounds: { x: Math.max(0, rect.left), y, width: Math.min(rect.width, innerWidth - rect.left), height }
      } : null).catch(() => {})
    }
    place()
    const observer = new ResizeObserver(place)
    if (area.current) observer.observe(area.current)
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
      void window.marvi.placeBrowser(null).catch(() => {})
    }
  }, [session.id, target])
  return <>
    {session.tabs.length > 1 && <div className="browser-actions" aria-label="Browser tabs">
      {session.tabs.map(item => <button key={item.id} aria-pressed={item.id === tab || (!tab && item === session.tabs[0])} onClick={() => setTab(item.id)}>{item.url || 'New tab'}</button>)}
    </div>}
    <div className="browser-viewport" ref={area} aria-label="Embedded browser" />
  </>
}

export function BrowserPage(): React.JSX.Element {
  const [status, setStatus] = useState<BrowserStatus | null>(null)
  const [profile, setProfile] = useState('default')
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [destination, setDestination] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const refresh = useCallback(async () => {
    try {
      setStatus(await window.marvi.getBrowser())
    } catch {
      setError('Browser service is unavailable. Check Marvi Gateway.')
    }
  }, [])
  useEffect(() => {
    void refresh()
    const timer = setInterval(() => {
      void refresh()
    }, 1500)
    return () => clearInterval(timer)
  }, [refresh])
  const run = async (operation: () => Promise<unknown>): Promise<void> => {
    setBusy(true)
    setError('')
    try {
      await operation()
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Browser operation failed')
    } finally {
      setBusy(false)
    }
  }
  const control = (session: BrowserSession, command: BrowserCommand): void => {
    void run(() => window.marvi.browserControl(session.id, session.revision, command))
  }
  const selected =
    status?.sessions.filter((s) => s.profile_id === profile && s.state !== 'closed') ?? []
  return (
    <ControlPage
      title="Browser"
      description="A saved browser workspace you and Marvi can use together."
    >
      {error && (
        <p role="alert" className="browser-error">
          {error}
        </p>
      )}
      {status?.private_input && (
        <div className="browser-private" role="status">
          <strong>PRIVATE INPUT · MARVI PAUSED</strong>
          <p>
            Enter your password or verification code directly in the website. Resume when you are
            finished.
          </p>
        </div>
      )}
      <ControlSection title="Workspace">
        <form
          className="browser-form"
          onSubmit={(event) => {
            event.preventDefault()
            void run(() =>
              window.marvi.startBrowser({
                profile_id: profile,
                url: url.trim(),
                objective: 'Browse'
              })
            )
          }}
        >
          <label>
            Saved profile
            <select value={profile} onChange={(event) => setProfile(event.target.value)}>
              {(status?.profiles ?? [{ id: 'default', label: 'Personal' }]).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Website
            <input
              type="url"
              placeholder="https://example.com"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
            />
          </label>
          <button disabled={busy || !status || selected.length > 0}>Open browser</button>
        </form>
        <p className="browser-note">
          Logins and site preferences stay in this profile when you close the browser. Websites can
          still require you to sign in again.
        </p>
      </ControlSection>
      {selected.map((session) => (
        <ControlSection key={session.id} title={session.objective}>
          <div className="browser-session" aria-live="polite">
            <span className="browser-state">{session.state.replaceAll('_', ' ')}</span>
            <p>{session.detail}</p>
          </div>
          <div className="browser-actions">
            <button
              disabled={busy || session.state === 'starting'}
              onClick={() => control(session, 'show')}
            >
              Show browser
            </button>
            <button
              disabled={busy || session.state === 'private'}
              onClick={() => control(session, 'pause')}
            >
              Take over
            </button>
            <button
              disabled={busy || session.state === 'private'}
              onClick={() => control(session, 'private')}
            >
              Private input
            </button>
            <button
              disabled={busy || !['private', 'paused', 'cancelled'].includes(session.state)}
              onClick={() => control(session, 'resume')}
            >
              Resume
            </button>
            <button disabled={busy} onClick={() => control(session, 'stop')}>
              Stop task
            </button>
            <button disabled={busy} onClick={() => control(session, 'close')}>
              Close browser
            </button>
          </div>
          {!status?.private_input && (
            <ul className="browser-tabs">
              {session.tabs.map((tab) => (
                <li key={tab.id}>{tab.url || 'New tab'}</li>
              ))}
            </ul>
          )}
          {session.host === 'embedded' && !['closed', 'failed'].includes(session.state) && <BrowserViewport session={session} />}
          {!status?.private_input && session.download && (
            <form
              className="browser-form"
              onSubmit={(event) => {
                event.preventDefault()
                const artifact = session.download!.artifact
                void run(async () => {
                  await window.marvi.browserSaveDownload(session.id, artifact, destination)
                  setDestination('')
                })
              }}
            >
              <p>Download staged · {session.download.bytes.toLocaleString()} bytes</p>
              <label>
                Save in workspace
                <input
                  value={destination}
                  placeholder="downloads/invoice.pdf"
                  onChange={(event) => setDestination(event.target.value)}
                />
              </label>
              <button disabled={busy || !destination.trim()}>Save download</button>
            </form>
          )}
        </ControlSection>
      ))}
      <ControlSection title="Profiles">
        <form
          className="browser-form"
          onSubmit={(event) => {
            event.preventDefault()
            void run(async () => {
              await window.marvi.browserProfile({ action: 'create', label: name })
              setName('')
            })
          }}
        >
          <label>
            Profile name
            <input
              value={name}
              maxLength={60}
              onChange={(event) => setName(event.target.value)}
              placeholder="Work"
            />
          </label>
          <button disabled={busy || !name.trim()}>Add profile</button>
          <button
            type="button"
            disabled={busy || !name.trim()}
            onClick={() => {
              void run(() =>
                window.marvi.browserProfile({ action: 'rename', profile_id: profile, label: name })
              )
            }}
          >
            Rename selected
          </button>
        </form>
        {profile !== 'default' && (
          <details className="browser-remove">
            <summary>Remove this profile</summary>
            <p>This deletes its saved logins and site data. Close its browser first.</p>
            <button
              disabled={busy || selected.length > 0}
              onClick={() => {
                void run(async () => {
                  await window.marvi.browserProfile({ action: 'delete', profile_id: profile })
                  setProfile('default')
                })
              }}
            >
              Delete selected profile and site data
            </button>
          </details>
        )}
      </ControlSection>
    </ControlPage>
  )
}
