import { useStore } from '@nanostores/react'
import { useEffect, useRef, useState } from 'react'

import appIcon from './assets/app-icon.png'
import { DynamicIsland } from './components/DynamicIsland'
import {
  $runtimeState,
  $voiceState,
  VOICE_PHASES,
  applyRuntimeState,
  cycleVoicePhase,
  type VoicePhase,
  type VoiceState
} from './store/voice-state'
import type {
  AuditEvent,
  ConnectedAccount,
  MemoryPage,
  RoomEvent,
  RuntimeStatus
} from '../../shared/runtime'
import type { IslandAlignment, IslandPlacement } from '../../main/island-window'
import { connectVoiceRoom } from './lib/livekit-room'

const NAV_ITEMS = [
  'Overview',
  'Voice',
  'Vision',
  'Room',
  'Accounts',
  'Memory',
  'Activity',
  'Settings',
  'Updates',
  'About'
] as const
type Page = (typeof NAV_ITEMS)[number]

interface BuildInfo {
  version: string
  commit: string
  buildTime: string
  platform: string
  arch: string
  updateChannel: string
}

function MainSurface(): React.JSX.Element {
  const voice = useStore($voiceState)
  const runtime = useStore($runtimeState)
  const [page, setPage] = useState<Page>('Overview')
  const [version, setVersion] = useState('0.1.0-dev.0')

  useEffect(() => {
    void window.marvi?.getVersion().then(setVersion)
    void window.marvi?.getRuntime().then(applyRuntimeState)
    return window.marvi?.onRuntime(applyRuntimeState)
  }, [])

  useEffect(() => {
    let disposed = false
    let disconnect: (() => void) | undefined
    void connectVoiceRoom()
      .then((room) => {
        if (disposed) void room.disconnect()
        else disconnect = () => void room.disconnect()
      })
      .catch(() => cycleVoicePhase('error'))
    return () => {
      disposed = true
      disconnect?.()
    }
  }, [])

  const previewPhase = (phase: VoicePhase): void => {
    cycleVoicePhase(phase)
    window.marvi?.previewAssistantState($voiceState.get())
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <header className="brand-block">
          <BrandIcon className="brand-icon-sidebar" />
          <div>
            <strong>MARVI OS</strong>
            <span>VOICE + VISION</span>
          </div>
        </header>

        <nav aria-label="Main navigation">
          {NAV_ITEMS.map((item, index) => (
            <button
              className={page === item ? 'nav-item active' : 'nav-item'}
              key={item}
              onClick={() => setPage(item)}
            >
              <span>{String(index + 1).padStart(2, '0')}</span>
              {item.toUpperCase()}
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          <span className="pulse-dot" /> ALWAYS ON
          <small>MIC + CAMERA LOCAL</small>
        </div>
      </aside>

      <main className="content">
        <header className="topbar">
          <div>
            <span className="eyebrow">{'// CONTROL CENTER'}</span>
            <h1>{page}</h1>
          </div>
          <div className="top-island-preview">
            <DynamicIsland state={voice} compact />
          </div>
        </header>

        {page === 'Overview' ? (
          <Overview runtime={runtime} voice={voice} onPreviewPhase={previewPhase} />
        ) : page === 'Settings' ? (
          <SettingsPanel runtime={runtime} />
        ) : page === 'About' ? (
          <AboutPanel fallbackVersion={version} runtime={runtime} />
        ) : page === 'Room' ? (
          <RoomPanel runtime={runtime} />
        ) : page === 'Activity' ? (
          <ActivityPanel />
        ) : page === 'Accounts' ? (
          <AccountsPanel />
        ) : page === 'Memory' ? (
          <MemoryPanel />
        ) : (
          <PagePanel page={page} version={version} />
        )}

        <footer className="statusbar">
          <span>
            <i className={`status-${runtime.state}`} /> GATEWAY {runtime.state.toUpperCase()}
          </span>
          <span>LIVEKIT {runtime.components.livekit?.state.toUpperCase() ?? 'UNKNOWN'}</span>
          <span>VOICE {voice.phase.toUpperCase()}</span>
          <span>
            MIC {voice.microphone ? 'ON' : 'OFF'} / CAM {voice.camera ? 'ON' : 'OFF'}
          </span>
          <span className={voice.yolo ? 'status-yolo' : ''}>
            {voice.yolo ? '⚡ YOLO' : 'CONFIRM'}
          </span>
          <span className="status-version">MARVI OS {version}</span>
        </footer>
      </main>
    </div>
  )
}

function Overview({
  runtime,
  voice,
  onPreviewPhase
}: {
  runtime: RuntimeStatus
  voice: VoiceState
  onPreviewPhase: (phase: VoicePhase) => void
}): React.JSX.Element {
  const services = [
    ['MARVI GATEWAY', runtime.components.gateway],
    ['LIVEKIT', runtime.components.livekit],
    ['VOICE', runtime.components.voice],
    ['SMART ROOM', runtime.components.room],
    ['ACCOUNTS', runtime.components.accounts]
  ] as const

  return (
    <section className="overview-grid">
      <article className="panel hero-panel">
        <div className="panel-label">01 / AMBIENT CORE</div>
        <div className="portrait-frame">
          <div className="portrait-glyph" aria-hidden="true">
            <span>╭──────────────╮</span>
            <span>│ M A R V I │</span>
            <span>│ ◉ ◉ │</span>
            <span>│ ─ │</span>
            <span>╰──────────────╯</span>
          </div>
          <div className="core-copy">
            <span className="eyebrow">CURRENT STATE</span>
            <strong>{voice.phase.toUpperCase()}</strong>
            <p>{voice.detail ?? 'Local senses armed. Waiting for a real event.'}</p>
          </div>
        </div>
        <div className="phase-controls" aria-label="Island preview state">
          {VOICE_PHASES.map((phase) => (
            <button
              className={voice.phase === phase ? 'phase active' : 'phase'}
              key={phase}
              onClick={() => onPreviewPhase(phase)}
            >
              {phase}
            </button>
          ))}
        </div>
      </article>

      <article className="panel services-panel">
        <div className="panel-label">02 / SYSTEMS</div>
        <div className="service-list">
          {services.map(([name, service]) => (
            <div className="service-row" key={name}>
              <span className="service-name">{name}</span>
              <span className={`service-state state-${service?.state ?? 'offline'}`}>
                {(service?.state ?? 'offline').toUpperCase()}
              </span>
              <small>{service?.detail ?? 'No status received'}</small>
            </div>
          ))}
        </div>
      </article>

      <article className="panel event-panel">
        <div className="panel-label">03 / LIVE CONTEXT</div>
        <div className="context-line">
          <span>ROOM</span>
          <strong>{runtime.components.room?.detail.toUpperCase() ?? 'OFFLINE'}</strong>
        </div>
        <div className="context-line">
          <span>VISION</span>
          <strong>{runtime.components.vision?.state.toUpperCase() ?? 'OFFLINE'}</strong>
        </div>
        <div className="context-line">
          <span>ACCOUNTS</span>
          <strong>{runtime.components.accounts?.detail.toUpperCase() ?? 'NOT CONNECTED'}</strong>
        </div>
        <div className="context-line">
          <span>MEMORY</span>
          <strong>FOUNDATION PENDING</strong>
        </div>
      </article>
    </section>
  )
}

interface RoomSnapshot {
  live: boolean
  stale?: boolean
  state: Record<string, unknown>
}

function readRecord(source: Record<string, unknown>, key: string): Record<string, unknown> {
  const value = source[key]
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function RoomPanel({ runtime }: { runtime: RuntimeStatus }): React.JSX.Element {
  const [snapshot, setSnapshot] = useState<RoomSnapshot | null>(null)
  const [events, setEvents] = useState<RoomEvent[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let disposed = false
    const load = async (): Promise<void> => {
      const [response, history] = await Promise.all([
        window.marvi?.getRoomState(),
        window.marvi?.getRoomEvents()
      ])
      if (disposed) return
      if (history) setEvents(history)
      if (!response || response.status !== 'executed' || !response.result) {
        setSnapshot(null)
        setError(response?.error ?? 'Marvi Gateway is unavailable')
        return
      }
      setSnapshot(response.result)
      setError(null)
    }
    void load()
    const timer = setInterval(() => void load(), 4_000)
    return () => {
      disposed = true
      clearInterval(timer)
    }
  }, [])

  const state = snapshot?.state ?? {}
  const light = readRecord(state, 'light')
  const presence = readRecord(state, 'presence')
  const modes = readRecord(state, 'modes')
  const location = readRecord(state, 'location')

  const rows: Array<[string, string]> = [
    ['MODE', String(modes.active_mode ?? 'unknown').toUpperCase()],
    [
      'LIGHT',
      light.on
        ? `ON ${String(light.brightness ?? '?')}% ${String(light.scene ?? 'custom').toUpperCase()}`
        : 'OFF'
    ],
    ['PRESENCE', presence.detected ? 'IN ROOM' : 'AWAY'],
    ['PHONE', location.home ? 'HOME' : String(location.zone ?? 'unknown').toUpperCase()]
  ]

  return (
    <section className="single-page panel">
      <div className="panel-label">{'// ROOM'}</div>
      <h2>Room</h2>
      <p>
        Live state from the smart-room sidecar. Marvi OS reads and requests; the sidecar keeps every
        device, automation, and history record.
      </p>

      <div className="context-line">
        <span>SIDECAR</span>
        <strong className={`service-state state-${runtime.components.room?.state ?? 'offline'}`}>
          {(runtime.components.room?.state ?? 'offline').toUpperCase()}
        </strong>
      </div>

      {snapshot?.stale ? (
        <div className="context-line">
          <span>FEED</span>
          <strong>STALE SNAPSHOT — SIDECAR UNREACHABLE</strong>
        </div>
      ) : null}

      <div className="ascii-divider">+------------------------------+</div>

      {error ? (
        <span className="construction">{error.toUpperCase()}</span>
      ) : (
        rows.map(([label, value]) => (
          <div className="context-line" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))
      )}

      <div className="panel-label">{'// ROOM EVENTS'}</div>
      {events.length === 0 ? (
        <span className="construction">NO NOTABLE ROOM EVENTS RECORDED</span>
      ) : (
        <div className="service-list">
          {events.map((event) => (
            <div className="service-row" key={event.id}>
              <span className="service-name">{event.type.toUpperCase()}</span>
              <span className="service-state">{event.at.slice(11, 19)}</span>
              <small>{event.summary}</small>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function MemoryPanel(): React.JSX.Element {
  const [page, setPage] = useState<MemoryPage>({ total: 0, entries: [], summary: {} })
  const [confirmClear, setConfirmClear] = useState(false)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let disposed = false
    const load = async (): Promise<void> => {
      const next = await window.marvi?.getMemory()
      if (!disposed && next) setPage(next)
    }
    void load()
    const timer = setInterval(() => void load(), 5_000)
    return () => {
      disposed = true
      clearInterval(timer)
    }
  }, [reload])

  const clearAll = async (): Promise<void> => {
    await window.marvi?.clearMemory()
    setConfirmClear(false)
    setReload((n) => n + 1)
  }

  return (
    <section className="single-page panel">
      <div className="panel-label">{'// MEMORY'}</div>
      <h2>Memory</h2>
      <p>
        A local SQLite store on this machine. Nothing is uploaded and no embedding model runs.
        Entries taken from email or the web stay marked untrusted and are re-wrapped whenever Marvi
        reads them back.
      </p>

      <div className="context-line">
        <span>ENTRIES</span>
        <strong>{page.total}</strong>
      </div>
      <div className="context-line">
        <span>FACTS</span>
        <strong>{(page.summary.facts ?? []).join(' / ').toUpperCase() || 'NONE'}</strong>
      </div>

      <div className="phase-controls">
        {confirmClear ? (
          <>
            <button className="phase active" onClick={() => void clearAll()}>
              delete everything
            </button>
            <button className="phase" onClick={() => setConfirmClear(false)}>
              cancel
            </button>
          </>
        ) : (
          <button className="phase" onClick={() => setConfirmClear(true)}>
            forget everything
          </button>
        )}
      </div>

      <div className="ascii-divider">+------------------------------+</div>

      {page.entries.length === 0 ? (
        <span className="construction">NOTHING REMEMBERED YET</span>
      ) : (
        <div className="service-list">
          {page.entries.map((entry) => (
            <div className="service-row" key={entry.id}>
              <span className="service-name">{entry.subject.toUpperCase()}</span>
              <span className={`service-state state-${entry.trusted ? 'ready' : 'error'}`}>
                {entry.trusted ? entry.kind.toUpperCase() : 'UNTRUSTED'}
              </span>
              <small>
                {entry.at.slice(0, 10)} / {entry.source}
              </small>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function AccountsPanel(): React.JSX.Element {
  const [accounts, setAccounts] = useState<ConnectedAccount[]>([])
  const [detail, setDetail] = useState('Loading')
  const [available, setAvailable] = useState(true)

  useEffect(() => {
    let disposed = false
    const load = async (): Promise<void> => {
      const page = await window.marvi?.getAccounts()
      if (disposed || !page) return
      setAccounts(page.accounts)
      setDetail(page.detail)
      setAvailable(page.available)
    }
    void load()
    const timer = setInterval(() => void load(), 30_000)
    return () => {
      disposed = true
      clearInterval(timer)
    }
  }, [])

  return (
    <section className="single-page panel">
      <div className="panel-label">{'// ACCOUNTS'}</div>
      <h2>Accounts</h2>
      <p>
        Connections are owned by Composio. Marvi OS holds no provider passwords and never runs an
        OAuth flow — connect or reconnect an account in Composio and it appears here.
      </p>

      <div className="context-line">
        <span>COMPOSIO</span>
        <strong>{available ? detail.toUpperCase() : 'NOT CONFIGURED'}</strong>
      </div>

      <div className="ascii-divider">+------------------------------+</div>

      {accounts.length === 0 ? (
        <span className="construction">
          {available ? 'NO ACCOUNTS CONNECTED' : 'SET COMPOSIO_API_KEY TO ENABLE ACCOUNTS'}
        </span>
      ) : (
        <div className="service-list">
          {accounts.map((account) => (
            <div className="service-row" key={account.toolkit}>
              <span className="service-name">{account.toolkit.toUpperCase()}</span>
              <span className={`service-state state-${account.connected ? 'ready' : 'error'}`}>
                {account.connected ? 'CONNECTED' : account.status.toUpperCase()}
              </span>
              <small>
                {account.needsReconnect
                  ? 'Authorisation ended. Reconnect this account in Composio.'
                  : 'Available for on-demand retrieval and actions.'}
              </small>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function ActivityPanel(): React.JSX.Element {
  const [events, setEvents] = useState<AuditEvent[]>([])

  useEffect(() => {
    let disposed = false
    const load = async (): Promise<void> => {
      const next = await window.marvi?.getAudit()
      if (!disposed && next) setEvents(next)
    }
    void load()
    const timer = setInterval(() => void load(), 3_000)
    return () => {
      disposed = true
      clearInterval(timer)
    }
  }, [])

  return (
    <section className="single-page panel">
      <div className="panel-label">{'// ACTIVITY'}</div>
      <h2>Activity</h2>
      <p>
        Append-only local audit of every tool decision. Nothing here is sent anywhere; YOLO
        executions are recorded exactly like confirmed ones.
      </p>
      <div className="ascii-divider">+------------------------------+</div>

      {events.length === 0 ? (
        <span className="construction">NO TOOL ACTIVITY RECORDED YET</span>
      ) : (
        <div className="service-list">
          {events.map((event, index) => (
            <div className="service-row" key={`${event.at}-${index}`}>
              <span className="service-name">{event.tool.toUpperCase()}</span>
              <span className={`service-state audit-${event.event}`}>
                {event.event.toUpperCase()}
              </span>
              <small>
                {event.at.slice(11, 19)} / {event.mode.toUpperCase()}
                {Object.keys(event.arguments).length > 0
                  ? ` / ${JSON.stringify(event.arguments)}`
                  : ''}
                {event.detail ? ` / ${event.detail}` : ''}
              </small>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function PagePanel({ page, version }: { page: Page; version: string }): React.JSX.Element {
  const descriptions: Record<Page, string> = {
    Overview: '',
    Voice:
      'Streaming STT, TTS, wake word, interruption, acoustic echo control, and device diagnostics.',
    Vision:
      'Always-on local presence and gesture processing. Frames leave the PC only for an explicit vision task.',
    Room: 'Status and events from D:\\smart-room-plugin. Marvi OS does not replace its automation authority.',
    Accounts: 'Composio connections for email, LinkedIn, X, and other world-context providers.',
    Memory: 'Durable facts, episodic events, retrieval controls, and forget/export operations.',
    Activity: 'Structured local event and tool audit timeline. No hidden outbound telemetry.',
    Settings:
      'Voice devices, wake behavior, startup, confirmation mode, and the explicit YOLO switch.',
    Updates:
      'Repository-owned Windows update status, release notes, channel, and explicit install handoff.',
    About: `Marvi OS ${version}. Local-first voice and vision assistant built on LiveKit Agents.`
  }

  return (
    <section className="single-page panel">
      <div className="panel-label">{`// ${page.toUpperCase()}`}</div>
      <h2>{page}</h2>
      <p>{descriptions[page]}</p>
      <div className="ascii-divider">+------------------------------+</div>
      <span className="construction">FOUNDATION ONLINE / FEATURE MODULE PENDING</span>
    </section>
  )
}

function BrandIcon({ className = '' }: { className?: string }): React.JSX.Element {
  return <img alt="Marvi OS" className={`brand-icon ${className}`} src={appIcon} />
}

function SettingsPanel({ runtime }: { runtime: RuntimeStatus }): React.JSX.Element {
  const [displays, setDisplays] = useState<Array<{ id: number; label: string; primary: boolean }>>(
    []
  )
  const [placement, setPlacement] = useState<IslandPlacement>({
    displayId: null,
    alignment: 'center'
  })

  useEffect(() => {
    void window.marvi?.getDisplays().then(setDisplays)
    void window.marvi?.getIslandPlacement().then(setPlacement)
  }, [])

  const updatePlacement = (next: IslandPlacement): void => {
    setPlacement(next)
    void window.marvi?.setIslandPlacement(next).then(setPlacement)
  }

  const setYolo = (enabled: boolean): void => {
    void window.marvi?.setYolo(enabled).then(applyRuntimeState)
  }

  return (
    <section className="settings-page" aria-label="Marvi OS settings">
      <div className="settings-section">
        <div>
          <span className="eyebrow">{'// ACTION AUTHORITY'}</span>
          <h2>CONFIRMATION MODE</h2>
          <p>
            The model requests confirmation when context requires it. YOLO bypasses every prompt.
          </p>
        </div>
        <button
          aria-checked={runtime.assistant.yolo}
          className={runtime.assistant.yolo ? 'mode-switch active' : 'mode-switch'}
          onClick={() => setYolo(!runtime.assistant.yolo)}
          role="switch"
          type="button"
        >
          {runtime.assistant.yolo ? '⚡ YOLO / AUTO ACCEPT' : 'CONFIRM / ASK ME'}
        </button>
      </div>

      <div className="settings-section">
        <div>
          <span className="eyebrow">{'// DYNAMIC ISLAND'}</span>
          <h2>PLACEMENT</h2>
          <p>Select the monitor and top-edge alignment. The recessed line remains click-through.</p>
        </div>
        <div className="placement-controls">
          <label>
            DISPLAY
            <select
              aria-label="Island display"
              onChange={(event) =>
                updatePlacement({
                  ...placement,
                  displayId: event.target.value === 'auto' ? null : Number(event.target.value)
                })
              }
              value={placement.displayId ?? 'auto'}
            >
              <option value="auto">AUTO / CURRENT</option>
              {displays.map((display) => (
                <option key={display.id} value={display.id}>
                  {display.label.toUpperCase()}
                  {display.primary ? ' / PRIMARY' : ''}
                </option>
              ))}
            </select>
          </label>
          <div className="alignment-buttons" aria-label="Island alignment">
            {(['left', 'center', 'right'] as IslandAlignment[]).map((alignment) => (
              <button
                aria-pressed={placement.alignment === alignment}
                className={placement.alignment === alignment ? 'active' : ''}
                key={alignment}
                onClick={() => updatePlacement({ ...placement, alignment })}
                type="button"
              >
                {alignment.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="settings-section device-summary">
        <div>
          <span>MICROPHONE</span>
          <strong>{runtime.assistant.microphone ? 'ALWAYS ON' : 'OFF'}</strong>
        </div>
        <div>
          <span>CAMERA</span>
          <strong>{runtime.assistant.camera ? 'ALWAYS ON' : 'OFF'}</strong>
        </div>
        <div>
          <span>GATEWAY</span>
          <strong>{runtime.state.toUpperCase()}</strong>
        </div>
      </div>
    </section>
  )
}

function AboutPanel({
  fallbackVersion,
  runtime
}: {
  fallbackVersion: string
  runtime: RuntimeStatus
}): React.JSX.Element {
  const [build, setBuild] = useState<BuildInfo>({
    version: fallbackVersion,
    commit: 'development',
    buildTime: 'development',
    platform: 'win32',
    arch: 'x64',
    updateChannel: 'local'
  })

  useEffect(() => {
    void window.marvi?.getBuildInfo().then(setBuild)
  }, [])

  const facts = [
    ['VERSION', build.version],
    ['COMMIT', build.commit],
    ['BUILD', build.buildTime],
    ['TARGET', `${build.platform} / ${build.arch}`],
    ['CHANNEL', build.updateChannel],
    [
      'GATEWAY',
      `${runtime.components.gateway?.state ?? runtime.state} / ${runtime.components.gateway?.detail ?? 'offline'}`
    ],
    [
      'LIVEKIT',
      `${runtime.components.livekit?.state ?? 'offline'} / ${runtime.components.livekit?.detail ?? 'not started'}`
    ],
    ['STT / TTS', runtime.components.voice?.detail ?? 'native bakeoff pending']
  ]

  return (
    <section className="about-page">
      <div className="about-identity">
        <BrandIcon className="brand-icon-about" />
        <div>
          <span className="eyebrow">{'// LOCAL VOICE + VISION SYSTEM'}</span>
          <h2>MARVI OS</h2>
          <p>Always-on Windows assistant built around a compact voice-first surface.</p>
        </div>
      </div>
      <dl className="about-facts">
        {facts.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <div className="about-actions">
        <button disabled type="button">
          CHECK FOR UPDATES / PENDING
        </button>
        <button disabled type="button">
          EXPORT DIAGNOSTICS / PENDING
        </button>
      </div>
      <p className="about-provenance">UPSTREAM PROVENANCE AND LICENSES / docs/UPSTREAM.md</p>
    </section>
  )
}

function IslandSurface(): React.JSX.Element {
  const voice = useStore($voiceState)
  const measureRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    void window.marvi?.getRuntime().then(applyRuntimeState)
    const unsubscribe = window.marvi?.onRuntime(applyRuntimeState)
    return unsubscribe
  }, [])

  useEffect(() => {
    window.marvi?.setIslandInteractive(
      voice.phase === 'confirmation' && Boolean(voice.confirmation)
    )
  }, [voice.confirmation, voice.phase])

  useEffect(() => {
    const element = measureRef.current
    if (!element) return

    const reportSize = (): void => {
      const bounds = element.getBoundingClientRect()
      window.marvi?.setIslandSize({ width: bounds.width, height: bounds.height })
    }
    const observer = new ResizeObserver(reportSize)
    observer.observe(element)
    reportSize()
    return () => observer.disconnect()
  }, [])

  return (
    <div className={`island-stage island-stage-${voice.phase}`}>
      <div className="island-measure" ref={measureRef}>
        <DynamicIsland
          onConfirmationDecision={(decision) => {
            if (!voice.confirmation) return
            void window.marvi
              ?.resolveConfirmation(voice.confirmation.token, decision)
              .then(applyRuntimeState)
          }}
          state={voice}
        />
      </div>
    </div>
  )
}

export default function App(): React.JSX.Element {
  const surface = new URLSearchParams(window.location.search).get('surface')
  return surface === 'island' ? <IslandSurface /> : <MainSurface />
}
