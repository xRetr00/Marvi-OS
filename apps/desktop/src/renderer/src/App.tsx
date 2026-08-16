import { useStore } from '@nanostores/react'
import { useCallback, useEffect, useRef, useState } from 'react'

import appIcon from './assets/app-icon.png'
import { BootFailureOverlay } from './components/BootFailureOverlay'
import { ConnectingOverlay } from './components/ConnectingOverlay'
import { DynamicIsland } from './components/DynamicIsland'
import { ElectricGazeBackground } from './components/ElectricGazeBackground'
import { HapticsProvider } from './components/HapticsProvider'
import { TitleBar } from './components/TitleBar'
import { ShellContextMenu } from './components/ui/shell-context-menu'
import {
  $runtimeState,
  $voiceState,
  VOICE_PHASES,
  applyRuntimeState,
  cycleVoicePhase,
  type VoicePhase,
  type VoiceState
} from './store/voice-state'
import {
  $backgroundMode,
  setBackgroundMode,
  setBackgroundOpacity,
  $backgroundOpacity
} from './store/background'
import { $translucency, setTranslucency } from './store/translucency'
import { haptic } from './lib/haptics'
import type {
  AuditEvent,
  ChatEntry,
  ConnectedAccount,
  IdentityStatus,
  InitiativeStatus,
  MemoryPage,
  MindDecision,
  ProviderPage,
  ProviderRow,
  UpdateChannel,
  UpdateCheck,
  UpdateResult,
  UpdateStatus,
  RoomEvent,
  RuntimeStatus,
  ServiceReport
} from '../../shared/runtime'
import type { IslandAlignment, IslandPlacement } from '../../main/island-window'
import { connectVoiceRoom } from './lib/livekit-room'

const NAV_ITEMS = [
  'Overview',
  'Voice',
  'Chat',
  'Vision',
  'Room',
  'Accounts',
  'Providers',
  'Identity',
  'Memory',
  'Mind',
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
  const translucency = useStore($translucency)
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

  useEffect(() => {
    // Mirror the persisted translucency lever to the main process on boot.
    window.marvi?.setTranslucency(translucency)
  }, [translucency])

  const previewPhase = (phase: VoicePhase): void => {
    haptic('selection')
    cycleVoicePhase(phase)
    window.marvi?.previewAssistantState($voiceState.get())
  }

  const navigate = (item: Page): void => {
    if (item !== page) haptic('tap')
    setPage(item)
  }

  return (
    <ShellContextMenu
      actions={[
        { label: 'Overview', onSelect: () => navigate('Overview') },
        { label: 'Settings', onSelect: () => navigate('Settings') },
        { label: 'About', onSelect: () => navigate('About') },
        { label: 'Reload Shell', onSelect: () => window.location.reload() },
        {
          label: voice.yolo ? 'Switch to Confirm mode' : 'Switch to YOLO mode',
          onSelect: () => void window.marvi?.setYolo(!voice.yolo).then(applyRuntimeState)
        }
      ]}
    >
      <div className="app-shell">
        <TitleBar page={page} />

        <div className="app-body">
          <ElectricGazeBackground />

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
                  onClick={() => navigate(item)}
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
                <DynamicIsland compact state={voice} />
              </div>
            </header>

            {page === 'Overview' ? (
              <Overview onPreviewPhase={previewPhase} runtime={runtime} voice={voice} />
            ) : page === 'Settings' ? (
              <SettingsPanel runtime={runtime} />
            ) : page === 'About' ? (
              <AboutPanel fallbackVersion={version} runtime={runtime} />
            ) : page === 'Room' ? (
              <RoomPanel runtime={runtime} />
            ) : page === 'Voice' ? (
              <VoicePanel runtime={runtime} />
            ) : page === 'Chat' ? (
              <ChatPanel />
            ) : page === 'Activity' ? (
              <ActivityPanel />
            ) : page === 'Accounts' ? (
              <AccountsPanel />
            ) : page === 'Providers' ? (
              <ProvidersPanel />
            ) : page === 'Identity' ? (
              <IdentityPanel />
            ) : page === 'Memory' ? (
              <MemoryPanel />
            ) : page === 'Mind' ? (
              <MindPanel />
            ) : page === 'Updates' ? (
              <UpdatesPanel version={version} />
            ) : (
              <PagePanel page={page} version={version} />
            )}

            <footer className="statusbar">
              <span>
                <i className={`status-${runtime.state}`} /> GATEWAY {runtime.state.toUpperCase()}
              </span>
              <span>LIVEKIT {runtime.components.livekit?.state.toUpperCase() ?? 'UNKNOWN'}</span>
              <span>VOICE {voice.phase.toUpperCase()}</span>
              <VoiceLevelMeter level={voice.level} />
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

        <ConnectingOverlay />
        <BootFailureOverlay />
      </div>
    </ShellContextMenu>
  )
}

/**
 * Live voice-level meter in the status bar — the the predecessor assistant-style context meter
 * adapted to the always-on voice loop: 8 ASCII cells filling with the current
 * assistant audio level so the shell reads "alive" at a glance.
 */
function VoiceLevelMeter({ level }: { level: number }): React.JSX.Element {
  const cells = 8
  const filled = Math.round(Math.min(1, Math.max(0, level)) * cells)
  return (
    <span aria-label={`Voice level ${filled} of ${cells}`} className="voice-level-meter">
      {'▮'.repeat(filled)}
      {'▯'.repeat(cells - filled)}
    </span>
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

function UpdatesPanel({ version }: { version: string }): React.JSX.Element {
  const [status, setStatus] = useState<UpdateStatus | null>(null)
  const [result, setResult] = useState<UpdateResult | null>(null)
  const [check, setCheck] = useState<UpdateCheck | null>(null)
  const [checking, setChecking] = useState(false)
  const [confirming, setConfirming] = useState(false)

  useEffect(() => {
    let disposed = false
    void (async () => {
      const [next, last] = await Promise.all([
        window.marvi?.getUpdateStatus(),
        window.marvi?.consumeUpdateResult()
      ])
      if (disposed) return
      if (next) setStatus(next)
      // Surfaced once, on the first launch after an update ran.
      if (last) setResult(last)
    })()
    return () => {
      disposed = true
    }
  }, [])

  const runCheck = useCallback(async (): Promise<void> => {
    setChecking(true)
    const outcome = await window.marvi?.checkForUpdate()
    setCheck(outcome ?? null)
    setChecking(false)
  }, [])

  const chooseChannel = useCallback(
    async (channel: UpdateChannel): Promise<void> => {
      await window.marvi?.setUpdateChannel(channel)
      setCheck(null)
      setStatus((current) => (current ? { ...current, channel } : current))
      void runCheck()
    },
    [runCheck]
  )

  const channel = status?.channel ?? 'release'

  return (
    <section className="single-page panel">
      <div className="panel-label">{'// UPDATES'}</div>
      <h2>Updates</h2>
      <p>
        Marvi OS updates itself from its own checkout, so each update also refreshes the code that
        performs the next one. The app quits, updates, and comes back. If anything fails the
        previous version is restored.
      </p>

      <div className="context-line">
        <span>VERSION</span>
        <strong>{version}</strong>
      </div>
      <div className="context-line">
        <span>CHANNEL</span>
        <strong>{channel.toUpperCase()}</strong>
      </div>
      <div className="context-line">
        <span>SELF-UPDATE</span>
        <strong>{status?.supported ? 'AVAILABLE' : 'NOT A GIT INSTALL'}</strong>
      </div>
      {status?.inProgress ? (
        <div className="context-line">
          <span>STATE</span>
          <strong>UPDATE IN PROGRESS</strong>
        </div>
      ) : null}

      {result ? (
        <div className="context-line">
          <span>LAST UPDATE</span>
          <strong>
            {result.status.toUpperCase()} — {result.message.toUpperCase()}
          </strong>
        </div>
      ) : null}

      {check ? (
        <div className="context-line">
          <span>AVAILABLE</span>
          <strong>
            {check.error
              ? check.error.toUpperCase()
              : check.upToDate
                ? 'UP TO DATE'
                : check.channel === 'dev'
                  ? `${check.behindBy} COMMITS BEHIND MAIN`
                  : `RELEASE ${(check.targetRef ?? '').toUpperCase()} AVAILABLE`}
          </strong>
        </div>
      ) : null}

      <div className="phase-controls">
        <button
          className={channel === 'release' ? 'phase active' : 'phase'}
          onClick={() => void chooseChannel('release')}
        >
          release
        </button>
        <button
          className={channel === 'dev' ? 'phase active' : 'phase'}
          onClick={() => void chooseChannel('dev')}
        >
          dev
        </button>
        <button className="phase" onClick={() => void runCheck()} disabled={checking}>
          {checking ? 'checking…' : 'check'}
        </button>
      </div>

      <div className="phase-controls">
        {!status?.supported ? (
          <span className="construction">
            THIS BUILD CANNOT SELF-UPDATE; REINSTALL FROM A RELEASE
          </span>
        ) : confirming ? (
          <>
            <button className="phase active" onClick={() => void window.marvi?.startUpdate()}>
              quit and update
            </button>
            <button className="phase" onClick={() => setConfirming(false)}>
              cancel
            </button>
          </>
        ) : (
          <button className="phase" onClick={() => setConfirming(true)}>
            install update
          </button>
        )}
      </div>
    </section>
  )
}

function MindPanel(): React.JSX.Element {
  const [status, setStatus] = useState<InitiativeStatus | null>(null)
  const [decisions, setDecisions] = useState<MindDecision[]>([])
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let disposed = false
    const load = async (): Promise<void> => {
      const [next, log] = await Promise.all([
        window.marvi?.getInitiative(),
        window.marvi?.getDecisions()
      ])
      if (disposed) return
      if (next) setStatus(next)
      if (log) setDecisions(log.decisions)
    }
    void load()
    const timer = setInterval(() => void load(), 5_000)
    return () => {
      disposed = true
      clearInterval(timer)
    }
  }, [reload])

  const toggle = async (): Promise<void> => {
    await window.marvi?.setInitiative(!(status?.paused ?? false))
    setReload((n) => n + 1)
  }

  return (
    <section className="single-page panel">
      <div className="panel-label">{'// MIND'}</div>
      <h2>Mind</h2>
      <p>
        Marvi decides from the event journal, not from a timer. Every decision below names the rule
        that caused it — including the decisions to stay quiet. Pausing stops decisions but keeps
        observing, so nothing is lost while initiative is off.
      </p>

      <div className="context-line">
        <span>INITIATIVE</span>
        <strong>{status?.paused ? 'PAUSED' : 'ACTIVE'}</strong>
      </div>
      <div className="context-line">
        <span>SCHEDULE</span>
        <strong>{status?.running ? 'RUNNING' : 'STOPPED'}</strong>
      </div>
      <div className="context-line">
        <span>PENDING EVENTS</span>
        <strong>{status?.pending_events ?? 0}</strong>
      </div>
      {Object.entries(status?.last_errors ?? {}).map(([job, error]) => (
        <div className="context-line" key={job}>
          <span>{job.toUpperCase()} ERROR</span>
          <strong>{error.slice(0, 60).toUpperCase()}</strong>
        </div>
      ))}

      <div className="phase-controls">
        <button className={status?.paused ? 'phase active' : 'phase'} onClick={() => void toggle()}>
          {status?.paused ? 'resume initiative' : 'pause initiative'}
        </button>
      </div>

      <div className="ascii-divider">+------------------------------+</div>

      {decisions.length === 0 ? (
        <span className="construction">NO DECISIONS YET</span>
      ) : (
        <div className="service-list">
          {decisions.map((decision) => (
            <div className="service-row" key={decision.id}>
              <span className="service-name">{decision.trigger.toUpperCase()}</span>
              <span
                className={`service-state state-${decision.surface === 'silent' ? 'offline' : 'ready'}`}
              >
                {decision.surface.toUpperCase()}
              </span>
              <small>
                {decision.at.slice(11, 19)} / {decision.rule}
                {decision.detail ? ` / ${decision.detail}` : ''} / {decision.provider} /{' '}
                {decision.latency_ms.toFixed(1)}ms
              </small>
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

const ACCESS_LABEL: Record<string, string> = {
  api: 'PAY AS YOU GO',
  plan: 'SUBSCRIPTION PLAN',
  local: 'LOCAL'
}

function ProviderCard({
  provider,
  onSave,
  onRefresh
}: {
  provider: ProviderRow
  onSave: (values: Record<string, string>) => Promise<void>
  onRefresh: () => Promise<void>
}): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const [secret, setSecret] = useState('')
  const [model, setModel] = useState(provider.models.main)
  const [acknowledged, setAcknowledged] = useState(provider.configured)
  const [busy, setBusy] = useState(false)
  const [signIn, setSignIn] = useState('')

  const keyEnv = provider.env.key
  const modelEnv = provider.env.model
  const oauth = provider.oauth
  const needsKey = provider.authType !== 'none' && keyEnv !== '' && oauth === null
  // A plan cannot be connected until its terms warning has actually been read.
  const blocked = provider.warning !== null && !acknowledged

  const save = async (values: Record<string, string>): Promise<void> => {
    setBusy(true)
    try {
      await onSave(values)
      setSecret('')
    } finally {
      setBusy(false)
    }
  }

  // Poll while a browser sign-in is in flight. The Gateway holds the flow; this
  // only asks whether the user has come back yet.
  useEffect(() => {
    if (signIn !== 'waiting') return undefined
    const timer = setInterval(async () => {
      const status = (await window.marvi?.pollOauth(provider.name)) as {
        state?: string
        detail?: string
      } | null
      if (!status) return
      if (status.state === 'connected') {
        setSignIn('')
        await onRefresh()
      } else if (status.state === 'failed' || status.state === 'timed out') {
        setSignIn(status.detail ?? status.state)
      }
    }, 1_500)
    return () => clearInterval(timer)
  }, [signIn, provider.name, onRefresh])

  const connectPlan = async (): Promise<void> => {
    setBusy(true)
    try {
      const started = await window.marvi?.startOauth(provider.name)
      setSignIn(started?.ok ? 'waiting' : (started?.detail ?? 'could not start sign-in'))
    } finally {
      setBusy(false)
    }
  }

  const disconnect = async (): Promise<void> => {
    setBusy(true)
    try {
      await window.marvi?.disconnectProvider(provider.name)
      setSignIn('')
      await onRefresh()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="service-row provider-row">
      <span className="service-name">{provider.label.toUpperCase()}</span>
      <span className={`service-state state-${provider.configured ? 'ready' : 'pending'}`}>
        {provider.cooldown
          ? `COOLING DOWN ${Math.round(provider.cooldown.seconds_remaining)}S`
          : oauth
            ? oauth.state.toUpperCase()
            : provider.configured
              ? 'CONNECTED'
              : 'NOT CONNECTED'}
      </span>
      <small>
        {ACCESS_LABEL[provider.accessPath]} / {provider.apiMode.replace(/_/g, ' ').toUpperCase()} /{' '}
        {provider.models.main || 'no model'}
      </small>
      {provider.cooldown ? (
        <small className="provider-cooldown">{provider.cooldown.reason}</small>
      ) : null}

      {provider.limits.windows.length > 0 ? (
        <small>
          LIMITS {provider.limits.windows.map(([win, cap]) => `${cap} / ${win}`).join(', ')}
          {provider.limits.readable ? '' : ' (not published over the API)'}
        </small>
      ) : null}

      {provider.usage.billable > 0 ? (
        <small>
          {provider.usage.billable.toLocaleString()} billable tokens
          {provider.usage.cachedInput > 0
            ? ` / ${provider.usage.cachedInput.toLocaleString()} served from cache`
            : ''}
        </small>
      ) : null}

      <button className="phase" type="button" onClick={() => setOpen(!open)}>
        {open ? 'CLOSE' : provider.configured ? 'EDIT' : 'CONNECT'}
      </button>

      {open ? (
        <div className="provider-form">
          {provider.warning ? (
            <label className="provider-warning">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(event) => setAcknowledged(event.target.checked)}
              />
              <span>{provider.warning}</span>
            </label>
          ) : null}

          {oauth ? (
            <>
              <small>
                Marvi never sees your password. Sign-in happens on the provider&apos;s own page in
                your browser; Marvi only receives the result
                {oauth.encrypted_at_rest ? ', encrypted to this Windows account' : ''}.
              </small>
              {oauth.client_id_set ? null : (
                <small className="provider-cooldown">
                  Set {oauth.client_id_env} first — Marvi does not ship vendor client IDs.
                </small>
              )}
              <div className="provider-actions">
                <button
                  className="phase"
                  type="button"
                  disabled={busy || blocked || !oauth.client_id_set || signIn === 'waiting'}
                  onClick={() => void connectPlan()}
                >
                  {blocked
                    ? 'READ THE WARNING FIRST'
                    : signIn === 'waiting'
                      ? 'WAITING FOR SIGN-IN'
                      : oauth.connected
                        ? 'SIGN IN AGAIN'
                        : 'SIGN IN'}
                </button>
                {oauth.connected ? (
                  <button
                    className="phase danger"
                    type="button"
                    disabled={busy}
                    onClick={() => void disconnect()}
                  >
                    DISCONNECT
                  </button>
                ) : null}
              </div>
              {signIn && signIn !== 'waiting' ? (
                <small className="provider-cooldown">{signIn}</small>
              ) : null}
            </>
          ) : needsKey ? (
            <input
              type="password"
              placeholder={provider.configured ? 'Replace the saved key' : keyEnv}
              value={secret}
              onChange={(event) => setSecret(event.target.value)}
            />
          ) : (
            <small>No credential needed. Start the server and Marvi will find it.</small>
          )}

          <input
            type="text"
            placeholder="Model"
            value={model}
            onChange={(event) => setModel(event.target.value)}
          />

          <div className="provider-actions">
            <button
              className="phase"
              type="button"
              disabled={busy || blocked || (needsKey && !secret && model === provider.models.main)}
              onClick={() =>
                void save({
                  ...(secret ? { [keyEnv]: secret } : {}),
                  ...(model !== provider.models.main ? { [modelEnv]: model } : {})
                })
              }
            >
              {blocked ? 'READ THE WARNING FIRST' : busy ? 'SAVING' : 'SAVE'}
            </button>
            {provider.configured && needsKey ? (
              <button
                className="phase danger"
                type="button"
                disabled={busy}
                onClick={() => void save({ [keyEnv]: '' })}
              >
                DISCONNECT
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function ProvidersPanel(): React.JSX.Element {
  const [page, setPage] = useState<ProviderPage | null>(null)
  const [error, setError] = useState('')

  // Used by a card after a sign-in completes, so the page reflects it at once
  // rather than on the next poll.
  const load = useCallback(async (): Promise<void> => {
    const next = await window.marvi?.getProviders()
    setPage(next ?? null)
    setError(next ? '' : 'Marvi Gateway is unavailable')
  }, [])

  useEffect(() => {
    let disposed = false
    const poll = async (): Promise<void> => {
      const next = await window.marvi?.getProviders()
      if (disposed) return
      setPage(next ?? null)
      setError(next ? '' : 'Marvi Gateway is unavailable')
    }
    const timer = setInterval(() => void poll(), 20_000)
    void poll()
    return () => {
      disposed = true
      clearInterval(timer)
    }
  }, [])

  const save = async (values: Record<string, string>): Promise<void> => {
    const next = await window.marvi?.setProviderSettings(values)
    if (next) setPage(next)
    else setError('Could not save; the Gateway did not accept the change')
  }

  const groups: Array<[string, ProviderRow['accessPath']]> = [
    ['LOCAL', 'local'],
    ['PAY AS YOU GO', 'api'],
    ['SUBSCRIPTION PLANS', 'plan']
  ]

  return (
    <section className="single-page panel">
      <div className="panel-label">{'// PROVIDERS'}</div>
      <h2>Providers</h2>
      <p>
        Keys are written to a local settings file and never leave this machine. Budget is counted in
        tokens rather than money, because that is the one number every provider reports the same way
        — and the only one a subscription plan reports at all.
      </p>

      {page ? (
        <div className="context-line">
          <span>TOKENS USED</span>
          <strong>
            {page.totals.billable.toLocaleString()} BILLABLE
            {page.totals.cachedInput > 0
              ? ` / ${page.totals.cachedInput.toLocaleString()} CACHED`
              : ''}
          </strong>
        </div>
      ) : null}

      <div className="ascii-divider">+------------------------------+</div>

      {error ? <span className="construction">{error.toUpperCase()}</span> : null}

      {groups.map(([label, path]) => {
        const rows = (page?.providers ?? []).filter((row) => row.accessPath === path)
        if (rows.length === 0) return null
        return (
          <div key={path}>
            <div className="panel-label">{`// ${label}`}</div>
            <div className="service-list">
              {rows.map((provider) => (
                <ProviderCard
                  key={provider.name}
                  provider={provider}
                  onSave={save}
                  onRefresh={load}
                />
              ))}
            </div>
          </div>
        )
      })}
    </section>
  )
}

function IdentityPanel(): React.JSX.Element {
  const [identity, setIdentity] = useState<IdentityStatus | null>(null)
  const [soul, setSoul] = useState('')
  const [user, setUser] = useState('')
  const [saved, setSaved] = useState(true)

  useEffect(() => {
    let disposed = false
    void (async () => {
      const next = await window.marvi?.getIdentity()
      if (disposed || !next) return
      setIdentity(next)
      setSoul(next.soul)
      setUser(next.user)
    })()
    return () => {
      disposed = true
    }
  }, [])

  const save = async (): Promise<void> => {
    const next = await window.marvi?.setIdentity({ soul, user })
    if (next) {
      setIdentity(next)
      setSaved(true)
    }
  }

  return (
    <section className="single-page panel">
      <div className="panel-label">{'// IDENTITY'}</div>
      <h2>Identity</h2>
      <p>
        Two files that go into every prompt: who Marvi is, and who it is speaking to. Anything true
        only sometimes belongs in Memory instead — this is what is true on every single turn, and
        every token here is paid on every turn including the voice path.
      </p>

      {identity ? (
        <div className="context-line">
          <span>BUDGET</span>
          <strong>
            {identity.tokens} / {identity.budget} TOKENS
            {identity.truncated ? ' — TRUNCATED' : ''}
          </strong>
        </div>
      ) : null}

      <div className="ascii-divider">+------------------------------+</div>

      <label className="identity-field">
        <span>SOUL.md — voice, temperament, refusals</span>
        <textarea
          rows={10}
          value={soul}
          onChange={(event) => {
            setSoul(event.target.value)
            setSaved(false)
          }}
        />
      </label>

      <label className="identity-field">
        <span>USER.md — name, hours, standing preferences</span>
        <textarea
          rows={10}
          value={user}
          onChange={(event) => {
            setUser(event.target.value)
            setSaved(false)
          }}
        />
      </label>

      <button className="phase" type="button" disabled={saved} onClick={() => void save()}>
        {saved ? 'SAVED' : 'SAVE'}
      </button>

      {identity ? <small>{identity.directory}</small> : null}
    </section>
  )
}

const SERVICE_LABEL: Record<string, string> = {
  gateway: 'MARVI GATEWAY',
  livekit: 'LIVEKIT SERVER',
  agent: 'VOICE AGENT'
}

const SERVICE_PURPOSE: Record<string, string> = {
  gateway: 'Tool router, memory, mind, and every provider call.',
  livekit: 'Local WebRTC media server. Not needed if LIVEKIT_URL points at the cloud.',
  agent: 'The LiveKit worker that speaks and listens.'
}

/**
 * Service health, with the reason when something is down.
 *
 * This exists because the shell used to show "gateway offline" and nothing
 * else, while the actual Python traceback went to a pipe nobody read.
 */
function ServiceHealth({ compact = false }: { compact?: boolean }): React.JSX.Element {
  const [services, setServices] = useState<ServiceReport[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    let disposed = false
    void window.marvi?.getServices().then((reports) => {
      if (!disposed) setServices(reports ?? [])
    })
    const stop = window.marvi?.onServices((reports) => setServices(reports))
    return () => {
      disposed = true
      stop?.()
    }
  }, [])

  if (services.length === 0) {
    return (
      <span className="construction">
        {compact ? 'NO SUPERVISED SERVICES' : 'SERVICES ARE MANAGED OUTSIDE MARVI'}
      </span>
    )
  }

  return (
    <div className="service-list">
      {services.map((service) => {
        const bad = service.state === 'failed' || service.state === 'gave up'
        return (
          <div className="service-row" key={service.name}>
            <span className="service-name">
              {SERVICE_LABEL[service.name] ?? service.name.toUpperCase()}
            </span>
            <span
              className={`service-state state-${
                service.state === 'running' ? 'ready' : bad ? 'error' : 'pending'
              }`}
            >
              {service.state.toUpperCase()}
            </span>
            <small>{SERVICE_PURPOSE[service.name] ?? ''}</small>
            <small className={bad ? 'provider-cooldown' : undefined}>
              {service.detail}
              {service.restarts > 0 ? ` / ${service.restarts} restart attempts` : ''}
            </small>

            {service.output.length > 0 ? (
              <>
                <button
                  className="phase"
                  type="button"
                  onClick={() => setExpanded(expanded === service.name ? null : service.name)}
                >
                  {expanded === service.name ? 'HIDE OUTPUT' : 'SHOW OUTPUT'}
                </button>
                {expanded === service.name ? (
                  <pre className="service-output">{service.output.join('\n')}</pre>
                ) : null}
              </>
            ) : null}

            {bad ? (
              <button
                className="phase"
                type="button"
                onClick={() => void window.marvi?.retryService(service.name)}
              >
                RETRY NOW
              </button>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

function VoicePanel({ runtime }: { runtime: RuntimeStatus }): React.JSX.Element {
  const voice = useStore($voiceState)
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [deviceError, setDeviceError] = useState('')

  useEffect(() => {
    let disposed = false
    void navigator.mediaDevices
      ?.enumerateDevices()
      .then((all) => {
        if (disposed) return
        setDevices(all.filter((device) => device.kind === 'audioinput'))
      })
      .catch(() => setDeviceError('Could not read audio devices'))
    return () => {
      disposed = true
    }
  }, [])

  const livekit = runtime.components.livekit
  const gateway = runtime.components.gateway

  return (
    <section className="single-page panel">
      <div className="panel-label">{'// VOICE'}</div>
      <h2>Voice</h2>
      <p>
        The voice session runs over LiveKit: the agent worker joins a local room, and this window
        joins the same room as a participant. Both need the Gateway, which issues the token and owns
        every tool the agent can call.
      </p>

      <div className="context-line">
        <span>SESSION</span>
        <strong>{voice.phase.toUpperCase()}</strong>
      </div>
      <div className="context-line">
        <span>GATEWAY</span>
        <strong>{(gateway?.detail ?? 'unknown').toUpperCase()}</strong>
      </div>
      <div className="context-line">
        <span>LIVEKIT</span>
        <strong>{(livekit?.detail ?? 'unknown').toUpperCase()}</strong>
      </div>

      <div className="ascii-divider">+------------------------------+</div>
      <div className="panel-label">{'// LOCAL SERVICES'}</div>
      <ServiceHealth />

      <div className="ascii-divider">+------------------------------+</div>
      <div className="panel-label">{'// MICROPHONES'}</div>
      {deviceError ? (
        <span className="construction">{deviceError.toUpperCase()}</span>
      ) : devices.length === 0 ? (
        <span className="construction">
          NO MICROPHONE VISIBLE / GRANT MICROPHONE PERMISSION TO LIST DEVICES
        </span>
      ) : (
        <div className="service-list">
          {devices.map((device) => (
            <div className="service-row" key={device.deviceId}>
              <span className="service-name">
                {(device.label || 'Unnamed input').toUpperCase()}
              </span>
              <span className="service-state">
                {device.deviceId === 'default' ? 'DEFAULT' : ''}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function ChatPanel(): React.JSX.Element {
  const [messages, setMessages] = useState<ChatEntry[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [available, setAvailable] = useState(true)
  const [pending, setPending] = useState<{ tool: string; token: string } | null>(null)
  const bottom = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let disposed = false
    void window.marvi?.getChat().then((page) => {
      if (disposed || !page) return
      setMessages(page.messages)
      setAvailable(page.available)
    })
    return () => {
      disposed = true
    }
  }, [])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy])

  const send = async (): Promise<void> => {
    const text = draft.trim()
    if (!text || busy) return
    setDraft('')
    setBusy(true)
    // Show the user's own line immediately; waiting for the round trip to
    // echo it back makes the window feel broken.
    setMessages((current) => [
      ...current,
      { id: -Date.now(), at: new Date().toISOString(), role: 'user', content: text, meta: {} }
    ])
    try {
      const reply = await window.marvi?.sendChat(text)
      const page = await window.marvi?.getChat()
      if (page) setMessages(page.messages)
      setPending(
        reply?.pending_confirmation
          ? {
              tool: reply.pending_confirmation.tool as string,
              token: reply.pending_confirmation.token as string
            }
          : null
      )
      if (reply?.error) {
        setMessages((current) => [
          ...current,
          {
            id: -Date.now(),
            at: new Date().toISOString(),
            role: 'error',
            content: reply.error,
            meta: {}
          }
        ])
      }
    } finally {
      setBusy(false)
    }
  }

  const resolve = async (decision: 'approve' | 'deny'): Promise<void> => {
    if (!pending) return
    await window.marvi?.resolveConfirmation(pending.token, decision)
    setPending(null)
  }

  const clear = async (): Promise<void> => {
    await window.marvi?.clearChat()
    setMessages([])
    setPending(null)
  }

  return (
    <section className="single-page panel chat-page">
      <div className="panel-label">{'// CHAT'}</div>
      <h2>Chat</h2>
      <p>
        The same Marvi as the voice session — same identity, same memory, same tools, same
        confirmations. Only the way you reach it is different.
      </p>

      {!available ? (
        <span className="construction">NO PROVIDER CONNECTED / OPEN PROVIDERS TO CONNECT ONE</span>
      ) : null}

      <div className="chat-log">
        {messages.length === 0 ? (
          <span className="construction">NO MESSAGES YET</span>
        ) : (
          messages.map((entry) => (
            <div className={`chat-turn chat-${entry.role}`} key={entry.id}>
              <span className="chat-role">
                {entry.role === 'tool' ? 'TOOL RESULT' : entry.role.toUpperCase()}
              </span>
              <div className="chat-body">{entry.content}</div>
            </div>
          ))
        )}
        {busy ? (
          <div className="chat-turn chat-assistant">
            <span className="chat-role">MARVI</span>
            <div className="chat-body chat-thinking">thinking</div>
          </div>
        ) : null}
        <div ref={bottom} />
      </div>

      {pending ? (
        <div className="chat-confirm">
          <span>
            {pending.tool.toUpperCase()} needs your approval. This is the same token the Island
            resolves.
          </span>
          <div className="provider-actions">
            <button className="phase active" type="button" onClick={() => void resolve('approve')}>
              APPROVE
            </button>
            <button className="phase danger" type="button" onClick={() => void resolve('deny')}>
              DENY
            </button>
          </div>
        </div>
      ) : null}

      <div className="chat-compose">
        <textarea
          rows={3}
          value={draft}
          placeholder="Ask Marvi something"
          disabled={busy || !available}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            // Enter sends, Shift+Enter breaks the line.
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              void send()
            }
          }}
        />
        <div className="provider-actions">
          <button
            className="phase active"
            type="button"
            disabled={busy || !draft.trim() || !available}
            onClick={() => void send()}
          >
            {busy ? 'SENDING' : 'SEND'}
          </button>
          <button
            className="phase danger"
            type="button"
            disabled={busy || messages.length === 0}
            onClick={() => void clear()}
          >
            CLEAR
          </button>
        </div>
      </div>
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
    Chat: 'Typed conversation with the same Marvi the voice session reaches.',
    Vision:
      'Always-on local presence and gesture processing. Frames leave the PC only for an explicit vision task.',
    Room: 'Status and events from D:\\smart-room-plugin. Marvi OS does not replace its automation authority.',
    Accounts: 'Composio connections for email, LinkedIn, X, and other world-context providers.',
    Providers: 'Model providers, credentials, models per job, and token usage.',
    Identity: 'SOUL.md and USER.md - who Marvi is, and who it is speaking to.',
    Memory: 'Durable facts, episodic events, retrieval controls, and forget/export operations.',
    Mind: 'Event-driven decisions, the rule behind each one, and the initiative switch.',
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
  const translucency = useStore($translucency)
  const backgroundMode = useStore($backgroundMode)
  const backgroundOpacity = useStore($backgroundOpacity)
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
      <div className="settings-section settings-services">
        <div>
          <span className="eyebrow">{'// LOCAL SERVICES'}</span>
          <h2>RUNTIME</h2>
          <p>
            Marvi starts these itself. When one will not start, the reason is its own output — shown
            here rather than discarded.
          </p>
        </div>
        <ServiceHealth compact />
      </div>

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
          <span className="eyebrow">{'// APPEARANCE'}</span>
          <h2>WINDOW + BACKDROP</h2>
          <p>Translucency shows the desktop through the window. The backdrop stays local.</p>
        </div>
        <div className="appearance-controls">
          <label>
            TRANSLUCENCY {translucency}
            <input
              aria-label="Window translucency"
              max={100}
              min={0}
              onChange={(event) => setTranslucency(Number(event.target.value))}
              type="range"
              value={translucency}
            />
          </label>
          <label>
            BACKDROP
            <select
              aria-label="Backdrop mode"
              onChange={(event) => setBackgroundMode(event.target.value as typeof backgroundMode)}
              value={backgroundMode}
            >
              <option value="electricGaze">ELECTRIC GAZE</option>
              <option value="none">OFF</option>
            </select>
          </label>
          <label>
            BACKDROP OPACITY {backgroundOpacity}
            <input
              aria-label="Backdrop opacity"
              disabled={backgroundMode !== 'electricGaze'}
              max={100}
              min={0}
              onChange={(event) => setBackgroundOpacity(Number(event.target.value))}
              type="range"
              value={backgroundOpacity}
            />
          </label>
        </div>
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
  return surface === 'island' ? (
    <IslandSurface />
  ) : (
    <HapticsProvider>
      <MainSurface />
    </HapticsProvider>
  )
}
