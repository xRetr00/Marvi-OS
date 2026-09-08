import { ChevronLeft, ChevronRight, ExternalLink, Plus, RotateCw, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { BrowserCommand, BrowserSession, BrowserStatus } from '../../../shared/browser'
import { ControlPage, ControlSection } from './control-surface'
import './browser-page.css'

function BrowserViewport({ session }: { session: BrowserSession }): React.JSX.Element {
  const area = useRef<HTMLDivElement>(null)
  const [tab, setTab] = useState('')
  const [address, setAddress] = useState('')
  const [error, setError] = useState('')
  const [navigating, setNavigating] = useState(false)
  const selectedTab = session.tabs.find((t) => t.id === tab) ?? session.tabs[0]
  useEffect(() => {
    if (session.active_tab) setTab(session.active_tab)
  }, [session.active_tab])
  useEffect(() => {
    setAddress(selectedTab?.url ?? '')
  }, [selectedTab?.url])
  const navigate = async (action: string): Promise<void> => {
    setNavigating(true)
    setError('')
    try {
      await window.marvi.browserAction(session.id, session.revision, action, {
        tab_id: selectedTab?.id,
        ...(['navigate', 'new_tab'].includes(action)
          ? { url: action === 'new_tab' ? '' : address }
          : {})
      })
    } catch {
      setError(
        'Navigation could not start. Wait for the current action or refresh the browser state.'
      )
    } finally {
      setNavigating(false)
    }
  }
  const disabled = navigating || !['ready', 'paused', 'cancelled'].includes(session.state)
  const lastTarget = useRef<string | undefined>(undefined)
  const target = session.tabs.find((t) => t.id === tab)?.target ?? session.tabs[0]?.target
  if (target) lastTarget.current = target
  useEffect(() => {
    const place = (): void => {
      if (!area.current) return
      const rect = area.current.getBoundingClientRect()
      const y = Math.max(80, rect.top)
      const height = Math.min(innerHeight - 30, rect.bottom) - y
      void window.marvi
        .placeBrowser(
          height > 0 && rect.width > 0
            ? {
                id: session.id,
                target: lastTarget.current,
                bounds: {
                  x: Math.max(0, rect.left),
                  y,
                  width: Math.min(rect.width, innerWidth - rect.left),
                  height
                }
              }
            : null
        )
        .catch(() => {})
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
  return (
    <div className="bx">
      {/* Tab strip. A browser's tabs belong at the top of the browser, not in
          a list under a form -- this used to render `session.tabs` as an
          unordered list beneath the controls. */}
      <div className="bx-tabs" role="tablist" aria-label="Browser tabs">
        {session.tabs.map((item) => (
          <button
            aria-selected={item.id === (tab || session.tabs[0]?.id)}
            className={`bx-tab${item.id === (tab || session.tabs[0]?.id) ? ' is-on' : ''}`}
            key={item.id}
            onClick={() => setTab(item.id)}
            role="tab"
            type="button"
          >
            <span>{titleOf(item.url)}</span>
          </button>
        ))}
        <button
          aria-label="New tab"
          className="bx-icon"
          disabled={disabled}
          onClick={() => void navigate('new_tab')}
          type="button"
        >
          <Plus aria-hidden="true" />
        </button>
        <span className="bx-gap" />
        {session.tabs.length > 1 ? (
          <button
            aria-label="Close tab"
            className="bx-icon"
            disabled={disabled}
            onClick={() => void navigate('close_tab')}
            type="button"
          >
            <X aria-hidden="true" />
          </button>
        ) : null}
      </div>

      {/* One row: navigation, then the address, the way every browser does it.
          It was two rows of labelled form fields. */}
      <form
        className="bx-bar"
        onSubmit={(event) => {
          event.preventDefault()
          void navigate('navigate')
        }}
      >
        <button
          aria-label="Back"
          className="bx-icon"
          disabled={disabled}
          onClick={() => void navigate('back')}
          type="button"
        >
          <ChevronLeft aria-hidden="true" />
        </button>
        <button
          aria-label="Forward"
          className="bx-icon"
          disabled={disabled}
          onClick={() => void navigate('forward')}
          type="button"
        >
          <ChevronRight aria-hidden="true" />
        </button>
        <button
          aria-label="Reload"
          className="bx-icon"
          disabled={disabled}
          onClick={() => void navigate('reload')}
          type="button"
        >
          <RotateCw aria-hidden="true" />
        </button>
        <input
          aria-label="Browser address"
          className="bx-url"
          disabled={disabled}
          onChange={(event) => setAddress(event.target.value)}
          placeholder={session.state === 'private' ? 'Private input' : 'Search or enter address'}
          type="text"
          value={session.state === 'private' ? '' : address}
        />
        <button
          aria-label="Open in your own browser"
          className="bx-icon"
          disabled={disabled || !address}
          onClick={() => void window.marvi.openExternal?.(address)}
          type="button"
        >
          <ExternalLink aria-hidden="true" />
        </button>
      </form>

      {error ? (
        <p className="bx-error" role="alert">
          {error}
        </p>
      ) : null}

      <div aria-label="Embedded browser" className="browser-viewport" ref={area} />
    </div>
  )
}

/** A tab's label: the site, not the whole URL. */
function titleOf(url: string): string {
  if (!url) return 'New tab'
  try {
    const { hostname, pathname } = new URL(url)
    const site = hostname.replace(/^www\./, '')
    return pathname.length > 1 ? `${site}${pathname}`.slice(0, 28) : site
  } catch {
    return url.slice(0, 28)
  }
}

export function BrowserPage({ onClose }: { onClose?: () => void } = {}): React.JSX.Element {
  const [status, setStatus] = useState<BrowserStatus | null>(null)
  const [profile, setProfile] = useState('default')
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [destination, setDestination] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [importResult, setImportResult] = useState('')
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
      {/* Only when it is a pane. Without a way out, a browser that opens
          beside the conversation is a browser you cannot put down. */}
      {onClose ? (
        <button
          aria-label="Close the browser pane"
          className="browser-close"
          onClick={onClose}
          type="button"
        >
          Close
        </button>
      ) : null}
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
          {session.host === 'embedded' && !['closed', 'failed'].includes(session.state) && (
            <BrowserViewport session={session} />
          )}
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
        <details>
          <summary>Import Chrome data into this profile</summary>
          <button
            disabled={busy}
            onClick={() => {
              void run(() => window.marvi.browserExportHelper())
            }}
          >
            Open Chrome cookie exporter
          </button>
          <p className="browser-note">
            In Chrome, open chrome://extensions, enable Developer mode, and Load unpacked from the
            exporter folder. Use its export button, then import the saved JSON below. You can remove
            the helper afterward.
          </p>
          <p className="browser-note">
            Close this profile first. Import cookies from a JSON export, or passwords exported as
            CSV from Chrome Password Manager → Settings → Export passwords. Chrome's encrypted
            profile folder cannot be copied directly.
          </p>
          <div className="browser-actions">
            {(['cookies', 'passwords'] as const).map((kind) => (
              <button
                key={kind}
                disabled={busy || selected.length > 0}
                onClick={() => {
                  void run(async () => {
                    const result = await window.marvi.browserImport(profile, kind)
                    if (result)
                      setImportResult(
                        `${result.imported} ${kind} imported; ${result.skipped} skipped. The source export was not deleted.`
                      )
                  })
                }}
              >
                Import {kind === 'cookies' ? 'cookie JSON' : 'password CSV'}
              </button>
            ))}
          </div>
          <p className="browser-note">
            Passwords stay encrypted on this Windows account. In a matching website, right-click and
            choose Fill saved login. Marvi pauses in Private input before filling; you submit the
            form and Resume yourself. Imported cookies can expire, and device-bound or partitioned
            sessions may need a fresh login.
          </p>
          {importResult && <p role="status">{importResult}</p>}
        </details>
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
