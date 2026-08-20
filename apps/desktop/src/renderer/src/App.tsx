import { useStore } from '@nanostores/react'
import { useCallback, useEffect, useRef, useState } from 'react'

import appIcon from './assets/app-icon.ico'
import { BootFailureOverlay } from './components/BootFailureOverlay'
import { AsciiRule } from './components/ui/ascii-rule'
import { ModelsPanel } from './components/models-panel'
import { Picker } from './components/ui/picker'
import { CommandCard } from './components/ui/command-card'
import { ConnectingOverlay } from './components/ConnectingOverlay'
import { DynamicIsland } from './components/DynamicIsland'
import { VoiceOrb } from './orb'
import { ElectricGazeBackground } from './components/ElectricGazeBackground'
import { HapticsProvider } from './components/HapticsProvider'
import { TitleBar } from './components/TitleBar'
import { ShellContextMenu } from './components/ui/shell-context-menu'
import { Chat } from './chat'

/** Settings shows the device rows in full words. "ALWAYS ON" was printed
 * unconditionally, including with the Gateway offline; "?" is the honest answer
 * when nothing has been able to look. */
const DEVICE_COPY: Record<DeviceState, string> = {
  on: 'ALWAYS ON',
  off: 'OFF',
  unknown: 'UNKNOWN'
}
import {
  $runtimeState,
  $voiceState,
  applyRuntimeState,
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
  ConnectedAccount,
  DeviceState,
  IdentityStatus,
  InitiativeStatus,
  MemoryPage,
  MindDecision,
  ModelPage,
  PluginPage,
  ProviderPage,
  ProviderRow,
  RoomEvent,
  RuntimeStatus,
  SchedulePage,
  ServiceReport,
  SkillReview,
  StoreSkill,
  UpdateChannel,
  UpdateCheck,
  UpdateResult,
  UpdateStatus,
  VoicePage
} from '../../shared/runtime'
import { deviceLabel, deviceState } from '../../shared/runtime'
import type { IslandAlignment, IslandPlacement } from '../../main/island-window'
import { $voiceLink, startVoice, stopVoice } from './store/voice-session'

/**
 * The sidebar, grouped by what a page is *for*.
 *
 * It was one flat list of eighteen entries numbered `01`..`18`. The numbers
 * implied an order that does not exist — nobody works through Marvi from
 * Overview to About — and a list that long with no structure is a list you
 * scan every time instead of learning. Five groups, each answering a different
 * question, and no numbers.
 */
/**
 * The sidebar: the things you use.
 *
 * Everything you *configure* moved behind the gear. Eighteen destinations in
 * one column meant scanning past ten pages you open twice a month to reach the
 * three you open constantly.
 */
const NAV_GROUPS = [
  { label: 'Talk', items: ['Overview', 'Voice', 'Chat'] },
  { label: 'World', items: ['Vision', 'Room', 'Activity'] },
  { label: 'Self', items: ['Identity', 'Memory', 'Mind'] }
] as const

/** Behind the gear: the things you set up. */
const SETTINGS_GROUPS = [
  { label: 'Connect', items: ['Providers', 'Models', 'Accounts', 'Skills', 'Plugins'] },
  { label: 'System', items: ['Preferences', 'Schedules', 'Maintenance', 'Updates', 'About'] }
] as const

type Page = (typeof NAV_GROUPS)[number]['items'][number]
type SettingsPage = (typeof SETTINGS_GROUPS)[number]['items'][number]

/** One line saying what the page is, shown under its title. A heading that only
 * repeats the sidebar entry spends the space without paying for it. */
const PAGE_BLURB: Record<Page, string> = {
  Overview: 'Everything at a glance, and what is not working',
  Voice: 'The live session, and what Marvi heard',
  Chat: 'The same assistant, typed',
  Vision: 'Who Marvi recognises, and what it does about visitors',
  Room: 'Lights, modes and presence, from the room plugin',
  Activity: 'What you have been doing, as context Marvi may use',
  Identity: 'Who Marvi is, and what it has learned about you',
  Memory: 'What Marvi remembers. Yours to read, export and delete',
  Mind: 'Why Marvi did things, and when it decided to act on its own'
}

const SETTINGS_BLURB: Record<SettingsPage, string> = {
  Providers: 'Credentials, sign-in, and what each has cost',
  Models: 'Which model answers, how hard it thinks, and who serves it',
  Accounts: 'Connected services, and what Marvi may do with them',
  Skills: 'Instructions Marvi can load for a task',
  Plugins: 'Backends Marvi runs, installed from a repository',
  Preferences: 'Behaviour, appearance and devices',
  Schedules: 'Reminders and checks Marvi runs on a clock',
  Maintenance: 'Installing models and diagnosing faults, from a terminal',
  Updates: 'Version, channel, and what changed',
  About: 'Build, licences and provenance'
}

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
  const [collapsed, setCollapsed] = useState(false)
  const [settings, setSettings] = useState<SettingsPage | null>(null)
  const [version, setVersion] = useState('0.1.0-dev.0')

  useEffect(() => {
    void window.marvi?.getVersion().then(setVersion)
    void window.marvi?.getRuntime().then(applyRuntimeState)
    return window.marvi?.onRuntime(applyRuntimeState)
  }, [])

  useEffect(() => {
    // Still automatic — an always-on assistant should be on when it opens.
    // The difference is that the handle now lives in a store, so the voice
    // page can end the session; before, it was trapped in this closure and
    // quitting the app was the only way to stop Marvi listening.
    void startVoice()
    return () => {
      void stopVoice()
    }
  }, [])

  useEffect(() => {
    // Mirror the persisted translucency lever to the main process on boot.
    window.marvi?.setTranslucency(translucency)
  }, [translucency])

  const navigate = (item: Page): void => {
    if (item !== page) haptic('tap')
    setPage(item)
  }

  return (
    <ShellContextMenu
      actions={[
        { label: 'Overview', onSelect: () => navigate('Overview') },
        { label: 'Settings', onSelect: () => setSettings('Preferences') },
        { label: 'About', onSelect: () => setSettings('About') },
        { label: 'Reload Shell', onSelect: () => window.location.reload() },
        {
          label: voice.yolo ? 'Switch to Confirm mode' : 'Switch to YOLO mode',
          onSelect: () => void window.marvi?.setYolo(!voice.yolo).then(applyRuntimeState)
        }
      ]}
    >
      <div className="app-shell">
        <TitleBar onSettings={() => setSettings('Preferences')} page={settings ?? page} />

        {/* The track width comes from the same state as the sidebar's. An
            `auto` track sizes to the item's max-content and stretches the item
            back to fill it, so the sidebar's own `width: 64px` was correct,
            applied, and visually ignored. */}
        <div className="app-body" style={{ gridTemplateColumns: `${collapsed ? 64 : 224}px 1fr` }}>
          <ElectricGazeBackground />

          {/* Width inline rather than by class. The stylesheet route lost a
              cascade race twice — first to a media query on the grid parent,
              then in a way I could not account for with the correct rule
              present and matching. One value, from the state that decides it,
              with nothing to override it. */}
          <aside
            className={collapsed ? 'sidebar collapsed' : 'sidebar'}
            style={{ overflow: 'hidden' }}
          >
            <header className="brand-block">
              <BrandIcon className="brand-icon-sidebar" />
              {/* "VOICE + VISION" was a tagline in a navigation column. The
                  collapse control earns the space instead. */}
              {!collapsed ? <strong>MARVI OS</strong> : null}
              <button
                aria-label={collapsed ? 'Expand the sidebar' : 'Collapse the sidebar'}
                className="sidebar-collapse"
                onClick={() => setCollapsed(!collapsed)}
                type="button"
              >
                <span aria-hidden="true">{collapsed ? '»' : '«'}</span>
              </button>
            </header>

            <nav aria-label="Main navigation">
              {NAV_GROUPS.map((group) => (
                <div className="nav-group" key={group.label}>
                  {!collapsed ? (
                    <h2 className="nav-group-label">{group.label.toUpperCase()}</h2>
                  ) : null}
                  {group.items.map((item) => (
                    <button
                      className={page === item ? 'nav-item active' : 'nav-item'}
                      key={item}
                      aria-current={page === item ? 'page' : undefined}
                      onClick={() => navigate(item)}
                      title={collapsed ? item : undefined}
                    >
                      {collapsed ? item.slice(0, 2).toUpperCase() : item.toUpperCase()}
                    </button>
                  ))}
                </div>
              ))}
            </nav>

            <div className="sidebar-foot">
              <span className={runtime.state === 'ready' ? 'pulse-dot' : ''} />{' '}
              {runtime.state === 'ready' ? 'ALWAYS ON' : runtime.state.toUpperCase()}
              <small>
                {/* Local processing is the claim worth making, and it is true
                    whatever state the Gateway is in. Whether the devices are
                    live is the status bar's job, and it now answers honestly. */}
                MIC + CAMERA STAY ON THIS MACHINE
              </small>
            </div>
          </aside>

          <main className="content">
            <header className="topbar">
              <div>
                <span className="eyebrow">
                  {`// ${(NAV_GROUPS.find((g) => (g.items as readonly string[]).includes(page))?.label ?? '').toUpperCase()}`}
                </span>
                <h1>{page}</h1>
              </div>
              <p className="topbar-blurb">{PAGE_BLURB[page]}</p>
            </header>

            {/* One scroll region for every page, so the top bar and status bar
                stay put and no page has to remember to handle its own
                overflow. */}
            <div className="page-scroll">
              {page === 'Overview' ? (
                <Overview runtime={runtime} voice={voice} />
              ) : page === 'Room' ? (
                <RoomPanel runtime={runtime} />
              ) : page === 'Voice' ? (
                <VoicePanel runtime={runtime} />
              ) : page === 'Chat' ? (
                <Chat />
              ) : page === 'Activity' ? (
                <ActivityPanel />
              ) : page === 'Identity' ? (
                <IdentityPanel />
              ) : page === 'Memory' ? (
                <MemoryPanel />
              ) : page === 'Mind' ? (
                <MindPanel />
              ) : (
                <PagePanel page={page} version={version} />
              )}
            </div>

            <footer className="statusbar">
              <span>
                <i className={`status-${runtime.state}`} /> GATEWAY {runtime.state.toUpperCase()}
              </span>
              <span>LIVEKIT {runtime.components.livekit?.state.toUpperCase() ?? 'UNKNOWN'}</span>
              <span>VOICE {voice.phase.toUpperCase()}</span>
              <VoiceLevelMeter level={voice.level} />
              <span>
                MIC {deviceLabel(deviceState(runtime, 'microphone'))} / CAM{' '}
                {deviceLabel(deviceState(runtime, 'camera'))}
              </span>
              <span className={voice.yolo ? 'status-yolo' : ''}>
                {voice.yolo ? '⚡ YOLO' : 'CONFIRM'}
              </span>
              <span className="status-version">MARVI OS {version}</span>
            </footer>
          </main>
        </div>

        {settings ? (
          <SettingsShell
            onClose={() => setSettings(null)}
            onNavigate={setSettings}
            page={settings}
            runtime={runtime}
            version={version}
          />
        ) : null}

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
  const value = Math.min(1, Math.max(0, level))
  const scaled = value * cells
  const full = Math.floor(scaled)
  const partial = scaled - full
  // A shade ramp reads as a continuous meter: ░ light → ▒ → ▓ dark → █ full.
  const shades = ['░', '▒', '▓'] as const
  const partialGlyph = partial > 0 ? shades[Math.min(2, Math.floor(partial * 3))] : ''
  const blocks = '█'.repeat(full) + partialGlyph + '░'.repeat(cells - full - (partialGlyph ? 1 : 0))
  return (
    <span aria-label={`Voice level ${Math.round(value * 100)}%`} className="voice-level-meter">
      {blocks}
    </span>
  )
}

function Overview({
  runtime,
  voice
}: {
  runtime: RuntimeStatus
  voice: VoiceState
}): React.JSX.Element {
  const services = [
    ['MARVI GATEWAY', runtime.components.gateway],
    ['LIVEKIT', runtime.components.livekit],
    ['VOICE', runtime.components.voice],
    ['SMART ROOM', runtime.components.room],
    ['ACCOUNTS', runtime.components.accounts]
  ] as const

  const blocked = services.filter(([, service]) => service && service.state !== 'ready')

  return (
    <section className="overview-grid">
      <article className="panel hero-panel">
        {/* Was an ASCII face and eight buttons that previewed island states —
            a developer toy on the first page the user sees. What belongs here
            is what Marvi is doing and what is stopping it. */}
        <div className="panel-label">{'// RIGHT NOW'}</div>
        <div className="overview-now">
          <span className="eyebrow">{voice.phase.toUpperCase()}</span>
          <strong>{voice.caption}</strong>
          <p>{voice.detail ?? 'Nothing is happening, which is the usual state.'}</p>
        </div>

        {blocked.length > 0 ? (
          <div className="overview-blockers">
            <span className="panel-label">{'// NEEDS ATTENTION'}</span>
            {blocked.map(([name, service]) => (
              <div className="context-line" key={name}>
                <span>{name}</span>
                <strong className={`state-${service?.state ?? 'offline'}`}>
                  {service?.detail ?? 'no status received'}
                </strong>
              </div>
            ))}
          </div>
        ) : (
          <p className="overview-clear">Everything Marvi needs is running.</p>
        )}

        <AsciiRule />
        <div className="panel-label">{'// HOW VOICE WORKS'}</div>
        <p className="overview-note">
          The voice session runs over LiveKit: the agent worker joins a local room and the app joins
          the same room as a participant. Both need the Gateway, which issues the token and owns
          every tool the agent can call.
        </p>
      </article>

      <article className="panel services-panel">
        <div className="panel-label">{'// SYSTEMS'}</div>
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
        <div className="panel-label">{'// LIVE CONTEXT'}</div>
        <div className="context-line">
          <span>ROOM</span>
          <strong>{runtime.components.room?.detail.toUpperCase() ?? 'OFFLINE'}</strong>
        </div>
        <div className="context-line">
          <span>VISION</span>
          <strong>{runtime.components.vision?.detail.toUpperCase() ?? 'OFFLINE'}</strong>
        </div>
        <div className="context-line">
          <span>ACCOUNTS</span>
          <strong>{runtime.components.accounts?.detail.toUpperCase() ?? 'NOT CONNECTED'}</strong>
        </div>
        <div className="context-line">
          <span>MICROPHONE</span>
          <strong>{DEVICE_COPY[deviceState(runtime, 'microphone')]}</strong>
        </div>
        <div className="context-line">
          <span>CAMERA</span>
          <strong>{DEVICE_COPY[deviceState(runtime, 'camera')]}</strong>
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

      <AsciiRule />

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

      <AsciiRule />

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

      <AsciiRule />

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

      <AsciiRule />

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

  // A local provider is configured the moment it has a default URL, which is
  // not the same as running. Saying CONNECTED for an Ollama that is not
  // started sends the user looking for the fault everywhere except the cause.
  const offline = provider.reachable === false
  const ready = provider.configured && !offline

  return (
    <div className="service-row provider-row">
      <span className="service-name">{provider.label.toUpperCase()}</span>
      <span className={`service-state state-${ready ? 'ready' : 'pending'}`}>
        {provider.cooldown
          ? `COOLING DOWN ${Math.round(provider.cooldown.seconds_remaining)}S`
          : offline
            ? 'NOT RUNNING'
            : oauth
              ? oauth.state.toUpperCase()
              : provider.configured
                ? 'CONNECTED'
                : 'NOT CONNECTED'}
      </span>
      {offline ? (
        <small className="provider-cooldown">
          Nothing is listening on {provider.baseUrl} — start it, or point{' '}
          {provider.env.url || 'the URL'} somewhere else.
        </small>
      ) : null}
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

      <AsciiRule />

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

      <AsciiRule />

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
  const link = useStore($voiceLink)
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
  const voiceComponent = runtime.components.voice

  // The one line that answers "why is nothing happening". Component detail is
  // written for exactly this: it names what is missing rather than restating
  // the state.
  const blocker =
    gateway?.state !== 'ready'
      ? gateway?.detail
      : voiceComponent?.state !== 'ready'
        ? voiceComponent?.detail
        : livekit?.state !== 'ready'
          ? livekit?.detail
          : ''

  const mood = voice.phase
  const speaking = voice.phase === 'speaking'
  const listening = voice.phase === 'listening' || voice.phase === 'wake'

  return (
    // The orb is the whole surface, header to status bar, and everything else
    // is laid over it. Facts in a column beside it made the page a diagram of
    // a voice assistant rather than one you look at.
    <section className="voice-page">
      <div className="voice-orb-surface">
        <VoiceOrb active={speaking || listening} level={voice.level} phase={voice.phase} />
      </div>

      {/* Top-left: what Marvi is doing, and what is stopping it. */}
      <div className="voice-hud voice-hud-state">
        <span className={`voice-hud-phase phase-${mood}`}>{voice.phase.toUpperCase()}</span>
        <strong>{voice.caption}</strong>
        {blocker ? <p className="voice-hud-blocker">{blocker}</p> : null}
      </div>

      {/* Top-right: what is actually doing the work. Not repeated from the
          status bar — that says whether things are up; this says which ones. */}
      <dl className="voice-hud voice-hud-rig">
        <div>
          <dt>LLM</dt>
          <dd>
            <VoiceModelPicker current={runtime.model?.llm ?? ''} />
          </dd>
        </div>
        <div>
          <dt>SPEECH IN</dt>
          <dd>{runtime.model?.stt || 'not installed'}</dd>
        </div>
        <div>
          <dt>SPEECH OUT</dt>
          <dd>{runtime.model?.tts || 'not installed'}</dd>
        </div>
        <div>
          <dt>MIC</dt>
          <dd>{deviceError ? 'unavailable' : microphoneLabel(devices)}</dd>
        </div>
      </dl>

      {/* Bottom-left: being in the room is a thing you can stop. It used to run
          from launch to quit with no control anywhere, which is the wrong
          default for a microphone. */}
      <div className="voice-hud voice-hud-session">
        <span className={`voice-link voice-link-${link}`}>
          {link === 'live' ? 'IN THE ROOM' : link === 'connecting' ? 'JOINING…' : 'NOT JOINED'}
        </span>
        {link === 'off' ? (
          <button className="phase" type="button" onClick={() => void startVoice()}>
            START
          </button>
        ) : (
          <button
            className="phase"
            type="button"
            disabled={link === 'connecting'}
            onClick={() => void stopVoice()}
          >
            END
          </button>
        )}
      </div>

      {/* Bottom: the live transcript, streaming. Two lines at most — this is a
          glance while talking, not a record; Chat is where a transcript lives. */}
      <div aria-live="polite" className="voice-transcript">
        {voice.heard ? (
          <p className="voice-heard">
            <span>YOU</span>
            {voice.heard}
          </p>
        ) : null}
        {voice.spoken ? (
          <p className="voice-spoken">
            <span>MARVI</span>
            {voice.spoken}
          </p>
        ) : null}
      </div>
    </section>
  )
}

/**
 * Which voice Marvi speaks in.
 *
 * Twenty-five ship with the TTS model and nothing listed any of them: the
 * voice was an environment variable holding a filename, so choosing one meant
 * knowing the naming convention and typing it exactly.
 *
 * No preview, and that is a limitation rather than an omission. These are
 * speaker embeddings, not samples — there is no audio to play without running
 * the TTS engine, which lives in the Agent's process and its own environment.
 */
function VoicePicker(): React.JSX.Element {
  const [page, setPage] = useState<VoicePage | null>(null)

  useEffect(() => {
    let gone = false
    void (async () => {
      const next = await window.marvi?.getVoices()
      if (!gone) setPage(next ?? null)
    })()
    return () => {
      gone = true
    }
  }, [])

  if (page && page.voices.length === 0) {
    return (
      <span className="construction">
        NO VOICES INSTALLED. RUN THE TTS INSTALLER FROM MAINTENANCE FIRST.
      </span>
    )
  }

  return (
    <div className="voice-choice">
      <Picker
        options={(page?.voices ?? []).map((voice) => ({
          value: voice.id,
          label: voice.name,
          detail: [voice.language, voice.gender].filter(Boolean).join(' · '),
          hint: voice.id
        }))}
        value={page?.selected ?? ''}
        onChange={(next) => {
          if (!page?.setting) return
          setPage({ ...page, selected: next, missing: false })
          void window.marvi?.setProviderSettings({ [page.setting]: next })
        }}
        placeholder="Model default"
        searchPlaceholder="Search voices…"
        empty="No voices installed."
      />
      {page?.missing ? (
        <span className="construction">
          {`THE CHOSEN VOICE "${page.selected}" IS NOT INSTALLED. MARVI WILL FALL BACK TO ITS DEFAULT.`}
        </span>
      ) : null}
    </div>
  )
}

/**
 * The model answering spoken turns.
 *
 * Sits in the rig readout rather than in settings because it is the number you
 * are most likely to want to change while listening to Marvi be slow. Unlike
 * the composer's, this one is persistent: voice has no session to scope a
 * choice to, so picking here writes the provider's configured model — the same
 * value the Models page sets.
 */
function VoiceModelPicker({ current }: { current: string }): React.JSX.Element {
  const [page, setPage] = useState<ModelPage | null>(null)
  const [providers, setProviders] = useState<ProviderPage | null>(null)
  const [chosen, setChosen] = useState(current)

  useEffect(() => {
    let gone = false
    void (async () => {
      const [models, settings] = await Promise.all([
        window.marvi?.getModels({}),
        window.marvi?.getProviders()
      ])
      if (gone) return
      setPage(models ?? null)
      setProviders(settings ?? null)
    })()
    return () => {
      gone = true
    }
  }, [])

  const rows = page?.providers ?? []
  if (rows.length === 0) return <>{current || 'not selected'}</>

  const options = rows.flatMap((row) =>
    row.models.map((model) => ({
      value: `${row.provider}::${model.id}`,
      label: model.name,
      detail: `${row.label} · ${model.id}`
    }))
  )

  const active =
    chosen && chosen.includes('::')
      ? chosen
      : (rows.find((row) => row.selected === (chosen || current))?.provider ?? '') +
        '::' +
        (chosen || current)

  return (
    <Picker
      className="voice-model-picker"
      options={options}
      value={active}
      onChange={(next) => {
        setChosen(next)
        const [provider, ...rest] = next.split('::')
        const env = providers?.providers.find((row) => row.name === provider)?.env.model
        if (env) void window.marvi?.setProviderSettings({ [env]: rest.join('::') })
      }}
      placeholder={current || 'not selected'}
      searchPlaceholder="Search models…"
    />
  )
}

/** The input Marvi will actually use, named rather than counted. "4 found"
 * tells you nothing about which one is live. */
function microphoneLabel(devices: MediaDeviceInfo[]): string {
  if (devices.length === 0) return 'none found'
  const preferred = devices.find((device) => device.deviceId === 'default') ?? devices[0]
  const name = (preferred.label || 'unnamed input').replace(/^Default\s*-\s*/i, '')
  return name.length > 28 ? `${name.slice(0, 27)}…` : name
}

function SchedulesPanel(): React.JSX.Element {
  const [page, setPage] = useState<SchedulePage | null>(null)
  const [name, setName] = useState('')
  const [when, setWhen] = useState('')
  const [message, setMessage] = useState('')
  const [insist, setInsist] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let disposed = false
    void (async () => {
      const next = await window.marvi?.getSchedules()
      if (!disposed && next) setPage(next)
    })()
    return () => {
      disposed = true
    }
  }, [])

  const add = async (): Promise<void> => {
    setError('')
    const next = await window.marvi?.addSchedule({ name, when, message, insist })
    if (!next) {
      setError('Marvi would not accept that. Check the time.')
      return
    }
    setPage(next)
    setName('')
    setWhen('')
    setMessage('')
    setInsist(false)
  }

  const act = async (
    id: number,
    action: 'remove' | 'enable' | 'disable' | 'run'
  ): Promise<void> => {
    const next = await window.marvi?.scheduleAction(id, action)
    if (next) setPage(next)
  }

  return (
    <section className="single-page panel">
      <div className="panel-label">{'// SCHEDULES'}</div>
      <h2>Schedules</h2>
      <p>
        Reminders and scheduled checks. A schedule re-times something Marvi can already do; it
        cannot introduce a new one. When it fires it writes an event and the usual rules decide how
        loud it may be.
      </p>

      {error ? <span className="construction">{error.toUpperCase()}</span> : null}

      <AsciiRule />
      <div className="panel-label">{'// NEW'}</div>

      <div className="schedule-form">
        <label>
          <span>NAME</span>
          <input
            value={name}
            placeholder="wake up"
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label>
          <span>WHEN</span>
          <input
            value={when}
            placeholder="07:30, 60 (minutes), or a cron expression"
            onChange={(event) => setWhen(event.target.value)}
          />
        </label>
        <label>
          <span>MESSAGE</span>
          <input
            value={message}
            placeholder="Time to get up"
            onChange={(event) => setMessage(event.target.value)}
          />
        </label>
        <label className="schedule-insist">
          <input
            type="checkbox"
            checked={insist}
            onChange={(event) => setInsist(event.target.checked)}
          />
          <span>
            SPEAK ANYWAY
            {/* The opt-in. Off by default because an hourly check firing out
                loud at 3am is what quiet hours exists to prevent. */}
            <small>Ignore quiet hours and sleep mode. For an alarm you mean.</small>
          </span>
        </label>
        <button
          className="phase"
          type="button"
          disabled={!name || !when}
          onClick={() => void add()}
        >
          ADD
        </button>
      </div>

      <AsciiRule />
      <div className="panel-label">{'// SET'}</div>

      <div className="service-list">
        {(page?.schedules ?? []).map((row) => (
          <div className="service-row" key={row.id}>
            <span className="service-name">{row.name.toUpperCase()}</span>
            <span
              className={`service-state state-${
                row.last_error ? 'error' : row.enabled ? 'ready' : 'pending'
              }`}
            >
              {row.last_error ? 'FAILED' : row.enabled ? 'ON' : 'OFF'}
              {row.insist ? ' / INSISTS' : ''}
            </span>
            <small>
              {row.kind === 'interval' ? `every ${row.expression} minutes` : row.expression} /{' '}
              {row.action}
            </small>
            {row.message ? <small>{row.message}</small> : null}
            {row.last_error ? (
              <small className="provider-cooldown">{row.last_error}</small>
            ) : row.last_run ? (
              <small>last run {row.last_run}</small>
            ) : null}
            <div className="provider-actions">
              <button className="phase" type="button" onClick={() => void act(row.id, 'run')}>
                RUN NOW
              </button>
              <button
                className="phase"
                type="button"
                onClick={() => void act(row.id, row.enabled ? 'disable' : 'enable')}
              >
                {row.enabled ? 'PAUSE' : 'RESUME'}
              </button>
              <button
                className="phase danger"
                type="button"
                onClick={() => void act(row.id, 'remove')}
              >
                REMOVE
              </button>
            </div>
          </div>
        ))}
      </div>

      {(page?.schedules ?? []).length === 0 ? (
        <span className="construction">NOTHING SCHEDULED</span>
      ) : null}
    </section>
  )
}

function PluginsPanel(): React.JSX.Element {
  const [page, setPage] = useState<PluginPage | null>(null)
  const [busy, setBusy] = useState('')
  const [confirming, setConfirming] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async (): Promise<void> => {
    const next = await window.marvi?.getPlugins()
    if (next) setPage(next)
  }, [])

  useEffect(() => {
    // Guarded rather than a bare `void load()`: navigating away mid-fetch would
    // otherwise set state on a panel that no longer exists.
    let disposed = false
    void (async () => {
      const next = await window.marvi?.getPlugins()
      if (!disposed && next) setPage(next)
    })()
    return () => {
      disposed = true
    }
  }, [])

  const act = async (name: string, action: 'install' | 'update' | 'remove'): Promise<void> => {
    setBusy(name)
    setError('')
    setConfirming('')
    try {
      const next = await window.marvi?.pluginAction(name, action)
      if (next) setPage(next)
      else setError(`${action} failed — see the Doctor page`)
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="single-page panel">
      <div className="panel-label">{'// PLUGINS'}</div>
      <h2>Plugins</h2>
      <p>
        Backends Marvi runs. A plugin is not a skill and not an MCP server: it ships a long-running
        process of its own and registers tools that talk to it. Its code runs inside Marvi and its
        dependencies install into Marvi, so adding one is a decision, not a download.
      </p>

      {error ? <span className="construction">{error.toUpperCase()}</span> : null}

      <AsciiRule />

      <div className="service-list">
        {(page?.plugins ?? []).map((plugin) => (
          <div className="service-row" key={plugin.name}>
            <span className="service-name">{plugin.title.toUpperCase()}</span>
            <span
              className={`service-state state-${
                !plugin.supported
                  ? 'error'
                  : plugin.installed
                    ? 'ready'
                    : busy === plugin.name
                      ? 'starting'
                      : 'pending'
              }`}
            >
              {busy === plugin.name
                ? 'WORKING'
                : plugin.installed
                  ? `INSTALLED ${plugin.version ? `v${plugin.version}` : ''}`.trim()
                  : plugin.detail.toUpperCase()}
            </span>
            {plugin.why ? <small>{plugin.why}</small> : null}
            <small className="plugin-repo">
              {plugin.repo}
              {plugin.ref ? ` (${plugin.ref})` : ' (default branch)'}
              {plugin.commit ? ` @${plugin.commit}` : ''}
            </small>
            {plugin.installed && !plugin.supported ? (
              <small className="provider-cooldown">{plugin.detail}</small>
            ) : null}
            {plugin.tools.length > 0 ? (
              <small>
                {plugin.tools.length} tools: {plugin.tools.join(', ')}
              </small>
            ) : null}

            {confirming === plugin.name ? (
              <div className="chat-confirm">
                <p>
                  {plugin.title} runs its own code inside Marvi and installs its dependencies into
                  Marvi&apos;s environment. Only install plugins you trust.
                </p>
                <div className="provider-actions">
                  <button
                    className="phase active"
                    type="button"
                    onClick={() => void act(plugin.name, 'install')}
                  >
                    INSTALL IT
                  </button>
                  <button className="phase" type="button" onClick={() => setConfirming('')}>
                    CANCEL
                  </button>
                </div>
              </div>
            ) : (
              <div className="provider-actions">
                {plugin.installed ? (
                  <>
                    <button
                      className="phase"
                      type="button"
                      disabled={!!busy}
                      onClick={() => void act(plugin.name, 'update')}
                    >
                      PULL LATEST
                    </button>
                    <button
                      className="phase danger"
                      type="button"
                      disabled={!!busy}
                      onClick={() => void act(plugin.name, 'remove')}
                    >
                      REMOVE
                    </button>
                  </>
                ) : (
                  <button
                    className="phase"
                    type="button"
                    disabled={!!busy}
                    onClick={() => setConfirming(plugin.name)}
                  >
                    INSTALL
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {(page?.plugins ?? []).length === 0 ? (
        <span className="construction">
          NO PLUGINS DECLARED / ADD ONE TO config/plugin-sources.json
        </span>
      ) : null}

      <AsciiRule />
      <button className="phase" type="button" onClick={() => void load()}>
        RE-CHECK
      </button>
      {page ? (
        <>
          <small>CHECKOUTS {page.install_root}</small>
          {/* Named because removing a plugin keeps its data, and someone
              looking for their room history should not have to guess. */}
          <small>PLUGIN DATA {page.data_root}</small>
        </>
      ) : null}
    </section>
  )
}

function SkillsPanel(): React.JSX.Element {
  const [store, setStore] = useState<StoreSkill[]>([])
  const [sources, setSources] = useState<string[]>([])
  const [filter, setFilter] = useState('')
  const [review, setReview] = useState<SkillReview | null>(null)
  const [busy, setBusy] = useState('')

  const load = useCallback(async (): Promise<void> => {
    const page = await window.marvi?.getSkillStore()
    if (page) {
      setStore(page.skills)
      setSources(page.sources)
    }
  }, [])

  useEffect(() => {
    let disposed = false
    void (async () => {
      const page = await window.marvi?.getSkillStore()
      if (disposed || !page) return
      setStore(page.skills)
      setSources(page.sources)
    })()
    return () => {
      disposed = true
    }
  }, [])

  const open = async (skill: StoreSkill): Promise<void> => {
    setBusy(skill.name)
    try {
      const reviewed = await window.marvi?.reviewSkill(skill.repo, skill.path)
      setReview(reviewed?.ok ? reviewed : null)
    } finally {
      setBusy('')
    }
  }

  const confirm = async (): Promise<void> => {
    if (!review?.staged) return
    setBusy('installing')
    try {
      await window.marvi?.installSkill(review.staged)
      setReview(null)
      await load()
    } finally {
      setBusy('')
    }
  }

  const remove = async (name: string): Promise<void> => {
    setBusy(name)
    try {
      await window.marvi?.removeSkill(name)
      await load()
    } finally {
      setBusy('')
    }
  }

  const shown = store.filter(
    (skill) =>
      !filter ||
      skill.name.includes(filter.toLowerCase()) ||
      skill.description.toLowerCase().includes(filter.toLowerCase())
  )

  return (
    <section className="single-page panel">
      <div className="panel-label">{'// SKILLS'}</div>
      <h2>Skills</h2>
      <p>
        Instructions that teach Marvi how to do something. A skill shapes behaviour, so you see what
        it says before it is installed — and a skill can never grant itself a tool it was not
        already allowed.
      </p>

      <div className="context-line">
        <span>SOURCES</span>
        <strong>{sources.join(', ').toUpperCase() || 'NONE CONFIGURED'}</strong>
      </div>

      <input
        className="skill-search"
        type="text"
        placeholder="Search skills"
        value={filter}
        onChange={(event) => setFilter(event.target.value)}
      />

      <AsciiRule />

      {/* The review sheet: instructions in full, warnings, then the button. */}
      {review ? (
        <div className="skill-review">
          <div className="panel-label">{`// ${review.skill.name.toUpperCase()}`}</div>
          <p>{review.skill.description}</p>
          {review.warnings.map((warning) => (
            <small className="provider-cooldown" key={warning}>
              {warning}
            </small>
          ))}
          {review.tools?.still_sensitive?.length ? (
            <small className="provider-cooldown">
              It names sensitive tools ({review.tools.still_sensitive.join(', ')}). Those still ask
              you every time.
            </small>
          ) : null}
          <pre className="service-output skill-body">{review.instructions}</pre>
          <div className="provider-actions">
            <button
              className="phase active"
              type="button"
              disabled={busy === 'installing'}
              onClick={() => void confirm()}
            >
              {busy === 'installing' ? 'INSTALLING' : 'INSTALL'}
            </button>
            <button className="phase" type="button" onClick={() => setReview(null)}>
              CANCEL
            </button>
          </div>
        </div>
      ) : null}

      {store.length === 0 ? (
        <span className="construction">LOADING THE STORE</span>
      ) : (
        <div className="service-list">
          {shown.map((skill) => (
            <div className="service-row" key={`${skill.repo}/${skill.name}`}>
              <span className="service-name">{skill.name.toUpperCase()}</span>
              <span className={`service-state state-${skill.installed ? 'ready' : 'pending'}`}>
                {skill.installed ? 'INSTALLED' : ''}
              </span>
              <small>{skill.description}</small>
              <small>{skill.repo}</small>
              <div className="provider-actions">
                {skill.installed ? (
                  <button
                    className="phase danger"
                    type="button"
                    disabled={!!busy}
                    onClick={() => void remove(skill.name)}
                  >
                    REMOVE
                  </button>
                ) : (
                  <button
                    className="phase"
                    type="button"
                    disabled={!!busy}
                    onClick={() => void open(skill)}
                  >
                    {busy === skill.name ? 'FETCHING' : 'VIEW & INSTALL'}
                  </button>
                )}
              </div>
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
      <AsciiRule />

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

function PagePanel({ page }: { page: Page; version: string }): React.JSX.Element {
  // The fallback for a sidebar page with no panel of its own. Only Vision
  // reaches it today; everything that used to land here now has a real page or
  // lives behind the gear.
  const descriptions: Record<Page, string> = {
    Overview: '',
    Voice: '',
    Chat: '',
    Room: '',
    Activity: 'Structured local event and tool audit timeline. No hidden outbound telemetry.',
    Identity: 'SOUL.md and USER.md - who Marvi is, and who it is speaking to.',
    Memory: 'Durable facts, episodic events, retrieval controls, and forget/export operations.',
    Mind: 'Event-driven decisions, the rule behind each one, and the initiative switch.',
    Vision:
      'Always-on local presence and gesture processing. The room plugin owns the camera; Marvi does not run a second loop on it.'
  }

  return (
    <section className="single-page panel">
      <div className="panel-label">{`// ${page.toUpperCase()}`}</div>
      <h2>{page}</h2>
      <p>{descriptions[page]}</p>
      <AsciiRule />
      <span className="construction">FOUNDATION ONLINE / FEATURE MODULE PENDING</span>
    </section>
  )
}

function BrandIcon({ className = '' }: { className?: string }): React.JSX.Element {
  return <img alt="Marvi OS" className={`brand-icon ${className}`} src={appIcon} />
}

/**
 * Everything you configure, in one overlay.
 *
 * Deliberately plain: no background video, no bordered panels stacked inside
 * bordered panels. Settings is a place you go to read a value and change it,
 * and the reported problem with the old pages was text sitting directly on a
 * moving image.
 */
function MaintenancePanel(): React.JSX.Element {
  return (
    <section className="single-page panel">
      <h2>Maintenance</h2>
      <p>
        Installing models and diagnosing faults run from a terminal. They are the tools you reach
        for when Marvi is not working, and a tool that needs Marvi to be working is the wrong tool
        for that job — the Setup page used to inspect the installation on a timer, which took the
        Gateway down while a model was downloading.
      </p>

      <AsciiRule />

      <CommandCard command="marvi doctor" title="// WHAT IS WRONG">
        <p>
          Checks dependencies, providers, storage, plugins and the build, and names the fix for each
          failure. Add <code>--fix</code> to apply the ones Marvi can do itself.
        </p>
      </CommandCard>

      <CommandCard command="marvi setup" title="// INSTALL WHAT IS MISSING">
        <p>
          Downloads and verifies models, browsers and dependencies. Name a capability to narrow it —{' '}
          <code>marvi setup voice</code> — or <code>--dry-run</code> to see the plan and the
          download size first.
        </p>
      </CommandCard>

      <CommandCard command="marvi models list" title="// WHAT IS INSTALLED">
        <p>
          Every component and its state. <code>marvi models verify &lt;name&gt;</code> checks one
          against its published hashes.
        </p>
      </CommandCard>

      <CommandCard command="marvi diagnostics" title="// FOR A BUG REPORT">
        <p>One redacted block with versions, component states and recent errors.</p>
      </CommandCard>

      <AsciiRule />
      <small>
        If <code>marvi</code> is not found, the installer puts it on PATH — open a new terminal, or
        run the bootstrap again to repair the installation.
      </small>
    </section>
  )
}

function SettingsShell({
  page,
  runtime,
  version,
  onNavigate,
  onClose
}: {
  page: SettingsPage
  runtime: RuntimeStatus
  version: string
  onNavigate: (next: SettingsPage) => void
  onClose: () => void
}): React.JSX.Element {
  useEffect(() => {
    const escape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', escape)
    return () => window.removeEventListener('keydown', escape)
  }, [onClose])

  return (
    <div className="settings-shell" role="dialog" aria-modal="true" aria-label="Settings">
      <nav className="settings-rail" aria-label="Settings sections">
        <div className="settings-rail-head">
          <strong>SETTINGS</strong>
          <button aria-label="Close settings" onClick={onClose} type="button">
            ✕
          </button>
        </div>
        {SETTINGS_GROUPS.map((group) => (
          <div className="settings-group" key={group.label}>
            <h2>{group.label.toUpperCase()}</h2>
            {group.items.map((item) => (
              <button
                aria-current={page === item ? 'page' : undefined}
                className={page === item ? 'settings-link active' : 'settings-link'}
                key={item}
                onClick={() => onNavigate(item)}
                type="button"
              >
                {item.toUpperCase()}
              </button>
            ))}
          </div>
        ))}
      </nav>

      <div className="settings-content">
        <header className="settings-head">
          <h1>{page}</h1>
          <p>{SETTINGS_BLURB[page]}</p>
        </header>
        <div className="settings-scroll">
          {page === 'Providers' ? (
            <ProvidersPanel />
          ) : page === 'Models' ? (
            <ModelsPanel />
          ) : page === 'Accounts' ? (
            <AccountsPanel />
          ) : page === 'Skills' ? (
            <SkillsPanel />
          ) : page === 'Plugins' ? (
            <PluginsPanel />
          ) : page === 'Preferences' ? (
            <SettingsPanel runtime={runtime} />
          ) : page === 'Schedules' ? (
            <SchedulesPanel />
          ) : page === 'Maintenance' ? (
            <MaintenancePanel />
          ) : page === 'Updates' ? (
            <UpdatesPanel version={version} />
          ) : (
            <AboutPanel fallbackVersion={version} runtime={runtime} />
          )}
        </div>
      </div>
    </div>
  )
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
          <span className="eyebrow">{'// SPEECH OUT'}</span>
          <h2>VOICE</h2>
          <p>
            The voices the TTS installer downloaded. Marvi speaks in the one chosen here.
          </p>
        </div>
        <VoicePicker />
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
          <strong>{DEVICE_COPY[deviceState(runtime, 'microphone')]}</strong>
        </div>
        <div>
          <span>CAMERA</span>
          <strong>{DEVICE_COPY[deviceState(runtime, 'camera')]}</strong>
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
    updateChannel: 'release'
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
  const runtime = useStore($runtimeState)
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
          camera={deviceState(runtime, 'camera')}
          microphone={deviceState(runtime, 'microphone')}
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
