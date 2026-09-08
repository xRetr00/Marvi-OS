import {
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  MoreVertical,
  Plus,
  RotateCw,
  X
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { BrowserCommand, BrowserSession, BrowserStatus } from '../../../shared/browser'
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
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
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
  const live = selected[0]
  return (
    <div className="bx-shell">
      {/* A browser, not a control panel.
          This rendered a `ControlPage` with a Workspace form, a Profiles
          section and an import expander -- all of it above the actual page,
          all of it visible before anything had been opened. The controls are
          still here; they are behind the menu, where a browser keeps them. */}
      <div className="bx-strip">
        <span className="bx-title">{live ? titleOf(live.tabs[0]?.url ?? '') : 'New tab'}</span>
        <span className="bx-gap" />
        <button
          aria-expanded={menuOpen}
          aria-label="Browser menu"
          className="bx-icon"
          onClick={() => setMenuOpen((open) => !open)}
          type="button"
        >
          <MoreVertical aria-hidden="true" />
        </button>
        {onClose ? (
          <button
            aria-label="Close the browser"
            className="bx-icon"
            onClick={onClose}
            type="button"
          >
            <X aria-hidden="true" />
          </button>
        ) : null}
      </div>

      {error ? (
        <p className="bx-error" role="alert">
          {error}
        </p>
      ) : null}

      {status?.private_input ? (
        <p className="bx-private" role="status">
          Private input · Marvi paused. Type your password in the page, then Resume.
        </p>
      ) : null}

      {live ? (
        <BrowserViewport session={live} />
      ) : (
        <form
          className="bx-open"
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
          <input
            aria-label="Website"
            onChange={(event) => setUrl(event.target.value)}
            placeholder="Type a URL"
            type="text"
            value={url}
          />
          <button disabled={busy || !status}>Open</button>
        </form>
      )}

      {menuOpen ? (
        <div className="bx-menu" role="menu">
          <label>
            Profile
            <select onChange={(event) => setProfile(event.target.value)} value={profile}>
              {(status?.profiles ?? [{ id: 'default', label: 'Personal' }]).map((one) => (
                <option key={one.id} value={one.id}>
                  {one.label}
                </option>
              ))}
            </select>
          </label>
          {live ? (
            <>
              <button onClick={() => control(live, 'show')} type="button">
                Bring to front
              </button>
              <button onClick={() => control(live, 'pause')} type="button">
                Take over
              </button>
              <button onClick={() => control(live, 'private')} type="button">
                Private input
              </button>
              <button
                disabled={!['private', 'paused', 'cancelled'].includes(live.state)}
                onClick={() => control(live, 'resume')}
                type="button"
              >
                Resume
              </button>
              <button onClick={() => control(live, 'stop')} type="button">
                Stop task
              </button>
              <button
                className="bx-danger"
                onClick={() => {
                  control(live, 'close')
                  setMenuOpen(false)
                }}
                type="button"
              >
                Close browser
              </button>
            </>
          ) : null}
          <p className="bx-note">
            Logins stay in this profile when the browser closes. Sites may still ask you to sign in.
          </p>
        </div>
      ) : null}
    </div>
  )
}
