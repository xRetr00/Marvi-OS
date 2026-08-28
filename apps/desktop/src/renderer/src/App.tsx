import { useStore } from '@nanostores/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import {
  Activity,
  Box,
  Brain,
  CalendarDays,
  Camera,
  CheckCircle2,
  Clock3,
  Database,
  Eye,
  FolderOpen,
  Gauge,
  History,
  House,
  KeyRound,
  Languages,
  Link2,
  Lightbulb,
  Info,
  Mic,
  Pause,
  Palette,
  Play,
  Power,
  Radio,
  RefreshCw,
  Route,
  Server,
  ShieldAlert,
  ShieldOff,
  Sparkles,
  SquareTerminal,
  Trash2,
  Unplug,
  Users,
  Waves,
  Wifi,
  Wrench
} from 'lucide-react'

import appIcon from './assets/app-icon.ico'
import { BootFailureOverlay } from './components/BootFailureOverlay'
import { ConversationBar } from './components/conversation-bar'
import { ModelsPanel } from './components/models-panel'
import { UsagePanel } from './components/usage-panel'
import { ProcessingCard } from './components/ui/processing-card'
import { Picker, type PickerOption } from './components/ui/picker'
import { CommandCard } from './components/ui/command-card'
import { ConnectingOverlay } from './components/ConnectingOverlay'
import { DynamicIsland } from './components/DynamicIsland'
import { VoiceOrb } from './orb'
import { ElectricGazeBackground } from './components/ElectricGazeBackground'
import { HapticsProvider } from './components/HapticsProvider'
import { TitleBar } from './components/TitleBar'
import { ShellContextMenu } from './components/ui/shell-context-menu'
import { Chat } from './chat'
import { AbstractIcon, type AbstractIconName } from './components/abstract-icon'
import { MessageTiming } from './components/message-timing'
import { ArcMemoryGraph } from './components/arc-memory-graph'
import { AboutUpdates, VersionPopover } from './components/update-controls'
import { TooltipProvider, UiTooltip } from './components/ui/tooltip'
import {
  ControlButton,
  ControlEmpty,
  ControlPage,
  ControlPill,
  ControlRow,
  ControlSection
} from './components/control-surface'

function stateTone(state: string | undefined): 'neutral' | 'ready' | 'warning' | 'danger' {
  if (state === 'ready' || state === 'connected' || state === 'active' || state === 'running') {
    return 'ready'
  }
  if (state === 'error' || state === 'failed') return 'danger'
  if (state === 'pending' || state === 'starting' || state === 'degraded') return 'warning'
  return 'neutral'
}

/** Settings shows the device rows in full words. "ALWAYS ON" was printed
 * unconditionally, including with the Gateway offline; "?" is the honest answer
 * when nothing has been able to look. */
const DEVICE_COPY: Record<DeviceState, string> = {
  on: 'ALWAYS ON',
  off: 'OFF',
  unknown: 'UNKNOWN'
}
import { $runtimeState, $voiceState, applyRuntimeState, type VoiceState } from './store/voice-state'
import {
  $backgroundMode,
  setBackgroundMode,
  setBackgroundOpacity,
  $backgroundOpacity
} from './store/background'
import { $translucency, setTranslucency } from './store/translucency'
import {
  $sessionMetrics,
  observeVoicePhase,
  sessionTimingStats,
  tickSession,
  updateSessionUsage
} from './store/session-metrics'
import { haptic } from './lib/haptics'
import type {
  AccountPage,
  AccountToolkit,
  FaceLibrary,
  AuditEvent,
  ConnectedAccount,
  DeviceState,
  IdentityStatus,
  InitiativeStatus,
  MemoryPage,
  MemoryEntry,
  MemoryImportPreview,
  MemoryImportRequest,
  MemoryImportResult,
  MemoryImportSources,
  MemoryGraphMode,
  MemoryGraphPage,
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
  SkillProposal,
  SkillsPage,
  StoreSkill,
  RoomVisionPreview,
  VoicePage,
  PendingQuestion,
  PendingSecret,
  LanguagePolicy,
  LanguageUpdate,
  MemoryPolicy,
  MemorySettingsUpdate,
  WakeStatus,
  WorkspacePolicy,
  WorkspaceUpdate
} from '../../shared/runtime'
import { deviceLabel, deviceState } from '../../shared/runtime'
import type { IslandAlignment, IslandPlacement } from '../../main/island-window'
import {
  DEFAULT_PET_PREFERENCES,
  type PetPreferences,
  type PetScale,
  type PetSide
} from '../../main/pet-window'
import { $heard, $spoken, subtitleTail } from './store/transcript'
import { deviceStanding, deviceStory, deviceTone } from './room-devices'
import { $voiceLink, sayAsUser, startVoice, stopVoice } from './store/voice-session'

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
  { label: 'Core', items: ['Overview', 'Voice', 'Chat'] },
  { label: 'Context', items: ['Vision', 'Room', 'Activity'] },
  { label: 'ARC', items: ['Identity', 'Graph', 'Mind'] }
] as const

/** Behind the gear: the things you set up. */
const SETTINGS_VOICE_PAGES = ['Speech recognition', 'Wake word', 'Voice synthesis'] as const

const SETTINGS_GROUPS = [
  {
    gapBefore: false,
    items: ['Providers', 'Models', 'Usage', 'Accounts', 'Skills', 'Memory', 'Plugins']
  },
  {
    gapBefore: true,
    items: ['Voice', 'Workspace', 'Appearance', 'Preferences', 'Schedules', 'Maintenance', 'About']
  }
] as const

type Page = (typeof NAV_GROUPS)[number]['items'][number]
type SettingsPage =
  | Exclude<(typeof SETTINGS_GROUPS)[number]['items'][number], 'Voice'>
  | (typeof SETTINGS_VOICE_PAGES)[number]

const NAV_CODES: Record<Page, string> = {
  Overview: 'OV',
  Voice: 'VO',
  Chat: 'CH',
  Vision: 'VI',
  Room: 'RM',
  Activity: 'AC',
  Identity: 'ID',
  Graph: 'GR',
  Mind: 'MI'
}

const NAV_ICONS: Record<Page, AbstractIconName> = {
  Overview: 'overview',
  Voice: 'voice',
  Chat: 'chat',
  Vision: 'vision',
  Room: 'room',
  Activity: 'activity',
  Identity: 'identity',
  Graph: 'memory',
  Mind: 'mind'
}

const SETTINGS_ICONS: Record<SettingsPage | 'Voice', AbstractIconName> = {
  Providers: 'providers',
  Models: 'models',
  Usage: 'activity',
  Accounts: 'accounts',
  Skills: 'skills',
  Memory: 'memory',
  Plugins: 'plugins',
  Voice: 'voice',
  'Speech recognition': 'microphone',
  'Voice synthesis': 'speaker',
  'Wake word': 'voice',
  Workspace: 'archive',
  Appearance: 'preferences',
  Preferences: 'preferences',
  Schedules: 'schedules',
  Maintenance: 'maintenance',
  About: 'about'
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

  useEffect(
    () =>
      window.marvi?.onNavigate((next) => {
        setSettings(null)
        setPage(next)
      }),
    []
  )

  useEffect(() => {
    let disposed = false
    const poll = async (): Promise<void> => {
      const usage = await window.marvi?.getUsage(false)
      if (!disposed && usage) updateSessionUsage(usage.totals)
    }
    void poll()
    const usageTimer = setInterval(() => void poll(), 4_000)
    const clockTimer = setInterval(() => tickSession(), 1_000)
    return () => {
      disposed = true
      clearInterval(usageTimer)
      clearInterval(clockTimer)
    }
  }, [])

  useEffect(() => {
    observeVoicePhase(voice.phase)
  }, [voice.phase])

  useEffect(() => {
    // Deliberately does not join. Marvi used to enter the room the moment the
    // app opened and stay there, which meant speech recognition running and a
    // model listening for as long as the window was open — a cost with no
    // conversation attached to it.
    //
    // A session is something you start: the Join button, or the wake word,
    // which is the same act without a keyboard. Both mean "listen now".
    //
    // It also fixed a race. The agent needs about twenty seconds to load its
    // speech models before it can accept work, and joining on open created
    // the room well inside that window — so no worker was available, no job
    // dispatched, and the page sat on READY with nothing behind it.
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

  const toggleSidebar = (): void => {
    const next = !collapsed
    haptic('selection')
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (!document.startViewTransition || reduceMotion) {
      setCollapsed(next)
      return
    }
    document.startViewTransition(() => {
      flushSync(() => setCollapsed(next))
    })
  }

  const statusbar = (
    <footer className="statusbar">
      <div className="statusbar-side">
        <UiTooltip label="Open Gateway health" side="top">
          <button className="status-item" onClick={() => navigate('Overview')} type="button">
            <Activity aria-hidden="true" />
            <span>Gateway</span>
            <span className="status-detail">{runtime.state}</span>
          </button>
        </UiTooltip>
        <UiTooltip label="Open realtime transport" side="top">
          <button className="status-item" onClick={() => navigate('Voice')} type="button">
            <Radio aria-hidden="true" />
            <span>RTC</span>
            <span className="status-detail">{runtime.components.livekit?.state ?? 'unknown'}</span>
          </button>
        </UiTooltip>
        <UiTooltip label="Open voice session" side="top">
          <button className="status-item" onClick={() => navigate('Voice')} type="button">
            <Waves aria-hidden="true" />
            <span>Voice</span>
            <span className="status-detail">{voice.phase}</span>
          </button>
        </UiTooltip>
        <WakeStatusItem onOpen={() => navigate('Voice')} />
        <VoiceLevelMeter level={voice.level} />
      </div>
      <div className="statusbar-side statusbar-side-right">
        <UiTooltip label="Open microphone and camera settings" side="top">
          <button className="status-item" onClick={() => setSettings('Preferences')} type="button">
            <Mic aria-hidden="true" />
            <span>Mic</span>
            <span className="status-detail">{deviceLabel(deviceState(runtime, 'microphone'))}</span>
            <Camera aria-hidden="true" />
            <span>Cam</span>
            <span className="status-detail">{deviceLabel(deviceState(runtime, 'camera'))}</span>
          </button>
        </UiTooltip>
        <UiTooltip label="Open confirmation mode settings" side="top">
          <button
            className={`status-item${voice.yolo ? ' status-yolo' : ''}`}
            onClick={() => setSettings('Preferences')}
            type="button"
          >
            <CheckCircle2 aria-hidden="true" />
            <span>{voice.yolo ? 'YOLO' : 'Confirm'}</span>
          </button>
        </UiTooltip>
        <VersionPopover version={version} onOpenAbout={() => setSettings('About')} />
      </div>
    </footer>
  )

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
        <TitleBar
          onSettings={() => setSettings('Preferences')}
          onToggleSidebar={page === 'Chat' ? undefined : toggleSidebar}
          page={settings ?? page}
          sidebarCollapsed={collapsed}
        />

        {/* The track width comes from the same state as the sidebar's. An
            `auto` track sizes to the item's max-content and stretches the item
            back to fill it, so the sidebar's own `width: 64px` was correct,
            applied, and visually ignored. */}
        <div
          className="app-body"
          style={{ gridTemplateColumns: `${page === 'Chat' ? 248 : collapsed ? 52 : 212}px 1fr` }}
        >
          <ElectricGazeBackground />

          {page === 'Chat' ? (
            <Chat onExit={() => navigate('Overview')} />
          ) : (
            <>
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
                  {!collapsed ? (
                    <span className="brand-copy">
                      <strong>MARVI</strong>
                      <small>LOCAL INTELLIGENCE</small>
                    </span>
                  ) : null}
                </header>

                <nav aria-label="Main navigation">
                  {NAV_GROUPS.map((group) => (
                    <div className="nav-group" key={group.label}>
                      {!collapsed ? (
                        <h2 className="nav-group-label">{group.label.toUpperCase()}</h2>
                      ) : null}
                      {group.items.map((item) => (
                        <UiTooltip key={item} label={item} side="right">
                          <button
                            className={page === item ? 'nav-item active' : 'nav-item'}
                            aria-label={item}
                            aria-current={page === item ? 'page' : undefined}
                            onClick={() => navigate(item)}
                          >
                            <AbstractIcon className="nav-icon" name={NAV_ICONS[item]} size={17} />
                            {!collapsed ? <span className="nav-label">{item}</span> : null}
                            {!collapsed ? (
                              <span className="nav-code">{NAV_CODES[item]}</span>
                            ) : null}
                          </button>
                        </UiTooltip>
                      ))}
                    </div>
                  ))}
                </nav>

                <div
                  aria-label={
                    runtime.state === 'ready' ? 'Local runtime ready' : `Runtime ${runtime.state}`
                  }
                  className="sidebar-foot"
                >
                  <span className={runtime.state === 'ready' ? 'pulse-dot' : ''} />{' '}
                  {runtime.state === 'ready' ? 'LOCAL / READY' : runtime.state.toUpperCase()}
                  <small>
                    MIC {deviceLabel(deviceState(runtime, 'microphone'))} + CAM{' '}
                    {deviceLabel(deviceState(runtime, 'camera'))} / LOCAL
                  </small>
                </div>
              </aside>

              <main className={page === 'Voice' ? 'content' : 'content control-content'}>
                {page === 'Voice' ? (
                  <header className="topbar">
                    <div>
                      <AbstractIcon className="topbar-icon" name={NAV_ICONS[page]} size={20} />
                      <h1>{page}</h1>
                    </div>
                    <span className="topbar-state">
                      {voice.phase.toUpperCase()} / {voice.caption}
                    </span>
                  </header>
                ) : null}

                {/* One scroll region for every page; shell chrome stays in its
                own tracks and no page has to manage window overflow. */}
                <div className="page-scroll">
                  {page === 'Overview' ? (
                    <Overview runtime={runtime} voice={voice} />
                  ) : page === 'Room' ? (
                    <RoomPanel runtime={runtime} view="room" />
                  ) : page === 'Vision' ? (
                    <RoomPanel runtime={runtime} view="vision" />
                  ) : page === 'Voice' ? (
                    <VoicePanel runtime={runtime} />
                  ) : page === 'Activity' ? (
                    <ActivityPanel />
                  ) : page === 'Identity' ? (
                    <IdentityPanel />
                  ) : page === 'Graph' ? (
                    <MemoryPanel />
                  ) : page === 'Mind' ? (
                    <MindPanel />
                  ) : (
                    <PagePanel page={page} />
                  )}
                </div>
              </main>
            </>
          )}
        </div>

        {statusbar}

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
    <span
      aria-label={`Voice level ${Math.round(value * 100)}%`}
      className={`voice-level-meter${value > 0.02 ? ' is-live' : ''}`}
    >
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
    ['MARVI GATEWAY', runtime.components.gateway, 'overview'],
    ['LIVEKIT', runtime.components.livekit, 'activity'],
    ['VOICE', runtime.components.voice, 'voice'],
    ['SMART ROOM', runtime.components.room, 'room'],
    ['ACCOUNTS', runtime.components.accounts, 'accounts']
  ] as const

  const path = [
    ['MICROPHONE', 'voice'],
    ['LIVEKIT', 'activity'],
    ['MARVI GATEWAY', 'overview'],
    ['VOICE', 'voice']
  ] as const

  const context = [
    ['ROOM', runtime.components.room?.detail.toUpperCase() ?? 'OFFLINE', 'room'],
    ['VISION', runtime.components.vision?.detail.toUpperCase() ?? 'OFFLINE', 'vision'],
    ['ACCOUNTS', runtime.components.accounts?.detail.toUpperCase() ?? 'NOT CONNECTED', 'accounts'],
    ['MICROPHONE', DEVICE_COPY[deviceState(runtime, 'microphone')], 'voice'],
    ['CAMERA', DEVICE_COPY[deviceState(runtime, 'camera')], 'vision']
  ] as const

  return (
    <ControlPage
      className="overview-control-page"
      description="Local assistant health, active session state, and connected context."
      title="Overview"
    >
      <ControlSection icon={Gauge} title="Current state">
        <ControlRow
          action={<ControlPill tone={stateTone(runtime.state)}>{voice.phase}</ControlPill>}
          description={voice.detail ?? 'Standing by.'}
          icon={Sparkles}
          title={voice.caption}
        />
      </ControlSection>

      <ControlSection
        description="The local path used by every spoken turn."
        icon={Route}
        title="Voice route"
      >
        <div className="control-route" aria-label="Voice route">
          {path.map(([label, icon], index) => (
            <div className="control-route-step" key={label}>
              <AbstractIcon name={icon} size={16} />
              <span>{label.toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase())}</span>
              {index < path.length - 1 ? <span aria-hidden="true">›</span> : null}
            </div>
          ))}
        </div>
      </ControlSection>

      <ControlSection icon={Server} title="Systems">
        {services.map(([name, service]) => (
          <ControlRow
            action={
              <ControlPill tone={stateTone(service?.state)}>
                {service?.state ?? 'offline'}
              </ControlPill>
            }
            description={service?.detail ?? 'No status received'}
            key={name}
            title={name.toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase())}
          />
        ))}
      </ControlSection>

      <ControlSection icon={Box} title="Context">
        {context.map(([label, value]) => (
          <ControlRow
            action={<span className="control-value">{value}</span>}
            key={label}
            title={label.toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase())}
          />
        ))}
      </ControlSection>
    </ControlPage>
  )
}

interface RoomSnapshot {
  live: boolean
  stale?: boolean
  state: Record<string, unknown>
  /**
   * Why the light in this state must not be reported as fact. Set by the
   * Gateway when the bulb is unconfigured, unreachable, or has not
   * acknowledged the state - all of which came back as a plain `on: false`
   * that this page rendered as "OFF" while the lamp was on.
   */
  caveat?: string
}

type RoomView = 'room' | 'vision'

const LIGHT_COLORS = [
  '#ff8c2a',
  '#ffd0a0',
  '#fff1dc',
  '#ffffff',
  '#7ca9ff',
  '#ad72ff',
  '#ed78d1',
  '#ff6d55'
]

const ROOM_MODES = [
  { id: 'normal', label: 'Normal', detail: '4000K · 70%' },
  { id: 'reading', label: 'Reading', detail: '3000K · 70%' },
  { id: 'focus', label: 'Focus', detail: '5000K · 100%' },
  { id: 'relax', label: 'Relax', detail: '2700K · 40%' },
  { id: 'night', label: 'Night', detail: 'Warm · 15%' },
  { id: 'sleep', label: 'Sleep', detail: 'Lights off' },
  { id: 'alarm', label: 'Alarm', detail: 'Bright alert' },
  { id: 'off', label: 'Off', detail: 'Lights off' }
] as const

function rgbToHex(value: unknown): string {
  if (!Array.isArray(value) || value.length !== 3) return '#ffffff'
  return `#${value
    .map((channel) =>
      Math.max(0, Math.min(255, Number(channel) || 0))
        .toString(16)
        .padStart(2, '0')
    )
    .join('')}`
}

function hexToRgb(value: string): number[] {
  return [1, 3, 5].map((offset) => Number.parseInt(value.slice(offset, offset + 2), 16))
}

function readRecord(source: Record<string, unknown>, key: string): Record<string, unknown> {
  const value = source[key]
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function RoomPanel({
  runtime,
  view
}: {
  runtime: RuntimeStatus
  view: RoomView
}): React.JSX.Element {
  const [snapshot, setSnapshot] = useState<RoomSnapshot | null>(null)
  const [events, setEvents] = useState<RoomEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  // `configured` and the broker come from `room_health`; `room_state` has the
  // failure counters. Reading either from the other is what showed every
  // device as "not set up" and the broker as `?:?`.
  const [health, setHealth] = useState<Record<string, unknown>>({})
  const [enrolling, setEnrolling] = useState(false)
  const [faceName, setFaceName] = useState('')
  const [library, setLibrary] = useState<FaceLibrary | null>(null)
  const [visitorNames, setVisitorNames] = useState<Record<number, string>>({})
  const [visionPreview, setVisionPreview] = useState<RoomVisionPreview | null>(null)
  const [lightDraft, setLightDraft] = useState({
    brightness: 70,
    colorTemp: 3000,
    color: '#ffffff'
  })

  useEffect(() => {
    let disposed = false
    const load = async (): Promise<void> => {
      const [response, history, live] = await Promise.all([
        window.marvi?.getRoomState(),
        window.marvi?.getRoomEvents(),
        window.marvi?.getRoomHealth()
      ])
      if (disposed) return
      if (history) setEvents(history)
      setHealth((live ?? {}) as Record<string, unknown>)
      if (!response || response.status !== 'executed' || !response.result) {
        setSnapshot(null)
        setError(response?.error ?? 'Marvi Gateway is unavailable')
        return
      }
      const nextLight = readRecord(response.result.state, 'light')
      setLightDraft({
        brightness: Number(nextLight.brightness ?? 70),
        colorTemp: Number(nextLight.color_temp ?? 3000),
        color: rgbToHex(nextLight.rgb)
      })
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

  useEffect(() => {
    if (view !== 'vision') return
    let disposed = false
    const load = async (): Promise<void> => {
      const next = await window.marvi?.getRoomVisionPreview()
      if (!disposed && next) setVisionPreview(next)
    }
    void load()
    // The preview stays responsive without turning the renderer into a
    // camera owner: each tick asks the sidecar for one bounded JPEG.
    const timer = setInterval(() => void load(), 500)
    return () => {
      disposed = true
      clearInterval(timer)
    }
  }, [view])

  const [busy, setBusy] = useState('')
  const [pressed, setPressed] = useState('')

  useEffect(() => {
    let disposed = false
    const load = async (): Promise<void> => {
      const known = await window.marvi?.getFaceLibrary()
      if (!disposed) setLibrary(known ?? null)
    }
    void load()
    // Slower than the state poll: these are images, and a face crop is written
    // when somebody is recognised rather than continuously.
    const timer = setInterval(() => void load(), 15_000)
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
  const vision = readRecord(state, 'vision')
  const mqtt = readRecord(health, 'mqtt')
  // Which Python libraries the sidecar is actually missing. Absent ones are
  // the reason for every failure beneath them, so they are said first.
  const libraries = readRecord(health, 'dependencies')
  const missing = {
    tuya: libraries.tinytuya === false ? 'tinytuya' : '',
    mqtt: libraries.paho_mqtt === false ? 'paho-mqtt' : ''
  }

  // The plugin has had `smart_room_vision_identity` all along and nothing in
  // the app ever called it, so the only way to teach the camera a face was to
  // ask out loud and hope. Enrolment reads several frames, so it takes a few
  // seconds and has to say so.
  const enrol = async (): Promise<void> => {
    const name = faceName.trim()
    if (!name) return
    setEnrolling(true)
    try {
      const answer = await window.marvi?.roomCommand('smart_room_vision_identity', {
        action: 'enroll_owner',
        name,
        seconds: 5
      })
      setPressed(
        answer?.status === 'executed'
          ? `Enrolled ${name}. Stand in front of the camera if it did not take.`
          : (answer?.error ?? 'The camera could not enrol that face.')
      )
      if (answer?.status === 'executed') setFaceName('')
      setLibrary((await window.marvi?.getFaceLibrary()) ?? null)
    } finally {
      setEnrolling(false)
    }
  }

  // Naming a face the camera did not recognise, or saying it is not one worth
  // keeping. The sighting carries its own crop, so this is a decision about a
  // picture rather than about a row number.
  const review = async (id: number, action: 'approve' | 'reject'): Promise<void> => {
    setEnrolling(true)
    try {
      const answer = await window.marvi?.roomCommand('smart_room_vision_identity', {
        action,
        sighting_id: id,
        ...(action === 'approve' ? { name: (visitorNames[id] ?? '').trim() } : {})
      })
      setPressed(
        answer?.status === 'executed'
          ? action === 'approve'
            ? `Named ${(visitorNames[id] ?? '').trim()}.`
            : 'Rejected.'
          : (answer?.error ?? 'The room refused that.')
      )
      setLibrary((await window.marvi?.getFaceLibrary()) ?? null)
    } finally {
      setEnrolling(false)
    }
  }

  const press = async (tool: string, args: Record<string, unknown>): Promise<void> => {
    setBusy(tool)
    try {
      const answer = await window.marvi?.roomCommand(tool, args)
      // A refusal is the interesting outcome: an unreachable bulb, a device
      // that has given up. Saying "done" over any of those is the same fault
      // as reporting a default as a reading.
      setPressed(
        answer?.status === 'executed'
          ? 'Accepted.'
          : answer?.status === 'confirmation_required'
            ? 'Waiting for your confirmation.'
            : (answer?.error ?? 'The room refused that.')
      )
    } finally {
      setBusy('')
    }
  }

  const camera = vision.camera_open
    ? 'ONLINE'
    : vision.running
      ? 'CONNECTING'
      : vision.enabled
        ? `OFF${vision.error ? ` — ${String(vision.error).toUpperCase()}` : ''}`
        : 'DISABLED'
  const people = Number(vision.person_count ?? 0)
  const owner = vision.owner_visible ? 'OWNER VISIBLE' : 'OWNER NOT VISIBLE'
  const gesture = vision.gesture
    ? String(vision.gesture).replaceAll('_', ' ').toUpperCase()
    : 'NONE'

  const roomRows: Array<[string, string]> = [
    ['MODE', String(modes.active_mode ?? 'unknown').toUpperCase()],
    [
      'LIGHT',
      // The Gateway says when this is a default rather than a reading: with no
      // broker and no key the sidecar returns on:false, brightness:0,
      // confirmed:false. Showing that as "OFF" is how the page came to
      // disagree with the lamp in the room.
      snapshot?.caveat
        ? 'UNKNOWN — NOT CONFIRMED'
        : light.on
          ? `ON ${String(light.brightness ?? '?')}% ${String(light.scene ?? 'custom').toUpperCase()}`
          : 'OFF'
    ],
    ['PRESENCE', presence.detected ? 'IN ROOM' : 'AWAY'],
    ['PHONE', location.home ? 'HOME' : String(location.zone ?? 'unknown').toUpperCase()]
  ]

  const visionRows: Array<[string, string]> = [
    ['VISION', camera],
    ['SEEN', `${people} ${people === 1 ? 'PERSON' : 'PEOPLE'} / ${owner}`],
    [
      'ACTIVITY',
      `${String(vision.activity ?? 'unknown').toUpperCase()} / ${String(vision.sleep_state ?? 'unknown').toUpperCase()}`
    ],
    ['GESTURE', gesture],
    ['VISITORS', `${Number(vision.pending_visitors ?? 0)} PENDING`]
  ]

  const visionEvents = events.filter((event) =>
    /vision|camera|face|gesture|presence|sleep|person/i.test(`${event.type} ${event.summary}`)
  )
  const lightKnown = Boolean(snapshot && !snapshot.caveat)
  const roomControlsDisabled = busy !== '' || !snapshot?.live

  const pageComponent = view === 'vision' ? runtime.components.vision : runtime.components.room
  const pageState = pageComponent?.state ?? 'offline'
  const pageDetail =
    pageComponent?.detail ??
    (view === 'vision' ? 'Room camera processing unavailable' : 'Smart Room unavailable')

  return (
    <ControlPage
      className={`room-page is-${view}`}
      description={
        view === 'vision'
          ? 'Local camera perception, identity review, and gesture observations.'
          : 'Live room state, direct controls, device health, and notable events.'
      }
      title={view === 'vision' ? 'Vision' : 'Room'}
    >
      <div className="room-runtime-head">
        <div className="room-runtime-copy">
          {view === 'vision' ? <Camera aria-hidden="true" /> : <House aria-hidden="true" />}
          <div>
            <strong>{view === 'vision' ? 'Room perception' : 'Smart Room'}</strong>
            <span>{snapshot?.stale ? 'Last known state · live feed unavailable' : pageDetail}</span>
          </div>
        </div>
        <ControlPill tone={stateTone(pageState)}>{pageState}</ControlPill>
      </div>

      {view === 'room' ? (
        <>
          <div className="room-workspace-grid">
            <ControlSection icon={Gauge} title="Live room">
              {error ? (
                <ControlEmpty
                  description={error}
                  icon={ShieldAlert}
                  title="Room state unavailable"
                />
              ) : (
                roomRows.map(([label, value]) => (
                  <ControlRow
                    action={<span className="control-value">{value}</span>}
                    key={label}
                    title={label.toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase())}
                  />
                ))
              )}
            </ControlSection>

            <section className="room-light-console" aria-labelledby="room-light-title">
              <header className="room-light-head">
                <div>
                  <Lightbulb aria-hidden="true" />
                  <div>
                    <h3 id="room-light-title">Light control</h3>
                    <p>Live control of the bulb, through the same tool Marvi uses.</p>
                  </div>
                </div>
                <ControlPill tone={lightKnown && light.on ? 'ready' : 'neutral'}>
                  {lightKnown ? (light.on ? 'powered on' : 'powered off') : 'unavailable'}
                </ControlPill>
              </header>

              {snapshot?.caveat ? (
                <div className="room-light-warning">
                  <ShieldAlert aria-hidden="true" />
                  <span>{snapshot.caveat}</span>
                </div>
              ) : null}

              <div className="room-light-layout">
                <div className="room-light-power">
                  <div
                    className={lightKnown && light.on ? 'room-light-orb is-on' : 'room-light-orb'}
                    style={{ backgroundColor: lightDraft.color }}
                  >
                    <Power aria-hidden="true" />
                  </div>
                  <strong>{lightKnown ? `${lightDraft.brightness}%` : '—'}</strong>
                  <span>
                    {lightKnown
                      ? `${lightDraft.colorTemp}K · ${String(light.scene ?? 'custom')}`
                      : 'No current reading'}
                  </span>
                  <div className="room-power-actions">
                    <ControlButton
                      aria-pressed={lightKnown && light.on === true}
                      className={lightKnown && light.on ? 'is-selected' : ''}
                      disabled={roomControlsDisabled}
                      onClick={() => void press('room_set_light', { on: true })}
                    >
                      On
                    </ControlButton>
                    <ControlButton
                      aria-pressed={lightKnown && light.on === false}
                      className={lightKnown && !light.on ? 'is-selected' : ''}
                      disabled={roomControlsDisabled}
                      onClick={() => void press('room_set_light', { on: false })}
                    >
                      Off
                    </ControlButton>
                  </div>
                </div>

                <div className="room-light-settings">
                  <label className="room-light-slider">
                    <span>
                      <b>Brightness</b>
                      <output>{lightDraft.brightness}%</output>
                    </span>
                    <input
                      aria-label="Light brightness"
                      disabled={roomControlsDisabled}
                      max={100}
                      min={1}
                      onChange={(event) =>
                        setLightDraft((current) => ({
                          ...current,
                          brightness: Number(event.target.value)
                        }))
                      }
                      onKeyUp={(event) =>
                        void press('room_set_light', {
                          on: true,
                          brightness: Number(event.currentTarget.value)
                        })
                      }
                      onPointerUp={(event) =>
                        void press('room_set_light', {
                          on: true,
                          brightness: Number(event.currentTarget.value)
                        })
                      }
                      type="range"
                      value={lightDraft.brightness}
                    />
                  </label>
                  <label className="room-light-slider is-temperature">
                    <span>
                      <b>White temperature</b>
                      <output>{lightDraft.colorTemp}K</output>
                    </span>
                    <input
                      aria-label="Light white temperature"
                      disabled={roomControlsDisabled}
                      max={6500}
                      min={2700}
                      onChange={(event) =>
                        setLightDraft((current) => ({
                          ...current,
                          colorTemp: Number(event.target.value)
                        }))
                      }
                      onKeyUp={(event) =>
                        void press('room_set_light', {
                          on: true,
                          color_temp: Number(event.currentTarget.value)
                        })
                      }
                      onPointerUp={(event) =>
                        void press('room_set_light', {
                          on: true,
                          color_temp: Number(event.currentTarget.value)
                        })
                      }
                      step={100}
                      type="range"
                      value={lightDraft.colorTemp}
                    />
                  </label>
                  <div className="room-light-color-row">
                    <span>
                      <Palette aria-hidden="true" /> Color
                    </span>
                    <div className="room-light-swatches">
                      <input
                        aria-label="Custom light color"
                        disabled={roomControlsDisabled}
                        onChange={(event) => {
                          const color = event.target.value
                          setLightDraft((current) => ({ ...current, color }))
                          void press('room_set_light', { on: true, rgb: hexToRgb(color) })
                        }}
                        type="color"
                        value={lightDraft.color}
                      />
                      {LIGHT_COLORS.map((color) => (
                        <button
                          aria-label={`Set light color ${color}`}
                          aria-pressed={lightDraft.color.toLowerCase() === color}
                          className="room-light-swatch"
                          disabled={roomControlsDisabled}
                          key={color}
                          onClick={() => {
                            setLightDraft((current) => ({ ...current, color }))
                            void press('room_set_light', { on: true, rgb: hexToRgb(color) })
                          }}
                          style={{ backgroundColor: color }}
                          type="button"
                        />
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              <div className="room-mode-grid" aria-label="Room modes">
                {ROOM_MODES.map((mode) => (
                  <button
                    aria-pressed={modes.active_mode === mode.id}
                    className={modes.active_mode === mode.id ? 'room-mode active' : 'room-mode'}
                    disabled={roomControlsDisabled}
                    key={mode.id}
                    onClick={() => void press('room_set_mode', { mode: mode.id })}
                    type="button"
                  >
                    <strong>{mode.label}</strong>
                    <span>{mode.detail}</span>
                  </button>
                ))}
              </div>
              {pressed ? <p className="room-command-result">{pressed}</p> : null}
            </section>
          </div>

          <ControlSection icon={Wifi} title="Devices and presence">
            {[
              ['Light (Tuya bulb)', 'tuya_bulb'],
              ['Socket (Tuya HE20)', 'tuya_he20'],
              ['Presence sensor (ESP32)', 'esp32']
            ].map(([label, key]) => {
              const device = readRecord(readRecord(health, 'devices'), key)
              const counters = readRecord(readRecord(state, 'devices'), key)
              const driver = key === 'esp32' ? '' : missing.tuya
              return (
                <ControlRow
                  action={
                    <ControlPill tone={deviceTone(driver, device)}>
                      {deviceStanding(driver, device)}
                    </ControlPill>
                  }
                  description={deviceStory(driver, device, counters)}
                  key={key}
                  title={label}
                />
              )
            })}
            <ControlRow
              action={
                <ControlPill tone={mqtt.connected ? 'ready' : missing.mqtt ? 'neutral' : 'danger'}>
                  {mqtt.connected ? 'connected' : 'disconnected'}
                </ControlPill>
              }
              description={
                missing.mqtt
                  ? `${missing.mqtt} is not installed, so MQTT is disabled.`
                  : mqtt.broker
                    ? `${String(mqtt.broker)}:${String(mqtt.port ?? 1883)}${
                        mqtt.connected ? '' : ' · no response'
                      }`
                    : 'No broker configured. Presence and phone location both depend on MQTT.'
              }
              title="MQTT broker"
            />
            <ControlRow
              action={
                <ControlPill tone={location.home ? 'ready' : 'neutral'}>
                  {location.home ? 'home' : String(location.zone ?? 'unknown')}
                </ControlPill>
              }
              description={
                location.source && location.source !== 'unknown'
                  ? `Reported by ${String(location.source)}`
                  : 'Nothing has reported a phone location yet.'
              }
              title="Phone (OwnTracks)"
            />
          </ControlSection>

          <ControlSection icon={History} title="Recent room events">
            {events.length === 0 ? (
              <ControlEmpty
                description="Notable presence, device, and room changes will appear here."
                icon={Clock3}
                title="No room events yet"
              />
            ) : (
              events.map((event) => (
                <ControlRow
                  action={<span className="control-time">{event.at.slice(11, 19)}</span>}
                  description={event.summary}
                  key={event.id}
                  title={event.type.replaceAll('_', ' ')}
                />
              ))
            )}
          </ControlSection>
        </>
      ) : (
        <>
          <div className="vision-workspace-grid">
            <div className="vision-stage" aria-label="Local camera processing status">
              {visionPreview?.available && visionPreview.image ? (
                <img
                  alt="Live Smart Room camera preview"
                  className="vision-preview-image"
                  src={visionPreview.image}
                />
              ) : (
                <div className="vision-stage-body">
                  <Camera aria-hidden="true" />
                  <strong>{camera === 'ONLINE' ? 'Waiting for a camera frame' : camera}</strong>
                  <p>
                    {visionPreview?.error ??
                      'The preview appears here when the local vision service has a frame.'}
                  </p>
                </div>
              )}
              <div className="vision-preview-badge">
                <span className={camera === 'ONLINE' ? 'is-live' : ''} />
                Local preview
              </div>
              <div className="vision-stage-status">
                <span>
                  {people} {people === 1 ? 'person' : 'people'}
                </span>
                <span>{vision.owner_visible ? 'owner visible' : 'owner not visible'}</span>
                <span>{gesture === 'NONE' ? 'no gesture' : gesture.toLowerCase()}</span>
              </div>
            </div>

            <ControlSection icon={Eye} title="Live perception">
              {error ? (
                <ControlEmpty
                  description={error}
                  icon={ShieldAlert}
                  title="Vision state unavailable"
                />
              ) : (
                visionRows.map(([label, value]) => (
                  <ControlRow
                    action={<span className="control-value">{value}</span>}
                    key={label}
                    title={label.toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase())}
                  />
                ))
              )}
            </ControlSection>
          </div>

          <ControlSection
            description={
              library?.owner
                ? `Owner: ${library.owner}`
                : 'No owner enrolled — the camera cannot distinguish you from visitors yet.'
            }
            icon={Users}
            title="Face identity"
          >
            <div className="face-identity-workspace">
              <div className="face-enrollment-card">
                <div className="face-enrollment-preview">
                  {visionPreview?.available && visionPreview.image ? (
                    <img alt="Current face enrollment preview" src={visionPreview.image} />
                  ) : (
                    <Camera aria-hidden="true" />
                  )}
                  <span>Live enrollment view</span>
                </div>
                <div className="face-enrollment-copy">
                  <span className="face-kicker">Enroll owner</span>
                  <strong>Keep one face centered in the preview</strong>
                  <p>
                    Marvi samples several frames locally. The reviewed embedding stays in the Smart
                    Room sidecar.
                  </p>
                  <div className="vision-enrol-actions">
                    <input
                      className="control-input"
                      disabled={enrolling}
                      onChange={(event) => setFaceName(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') void enrol()
                      }}
                      placeholder="Person name"
                      value={faceName}
                    />
                    <ControlButton
                      className="is-primary"
                      disabled={enrolling || !faceName.trim()}
                      onClick={() => void enrol()}
                    >
                      {enrolling ? 'Sampling…' : 'Enroll current face'}
                    </ControlButton>
                  </div>
                  {vision.error ? (
                    <span className="face-error">Camera unavailable: {String(vision.error)}</span>
                  ) : null}
                </div>
              </div>

              <div className="face-known-panel">
                <header>
                  <span className="face-kicker">Known people</span>
                  <strong>{library?.people.length ?? 0} enrolled</strong>
                </header>
                <div>
                  {(library?.people ?? []).length === 0 ? (
                    <p>No reviewed identities yet.</p>
                  ) : (
                    (library?.people ?? []).map((person) => (
                      <div className="face-known-row" key={person.name}>
                        <span className="face-avatar">{person.name.slice(0, 1).toUpperCase()}</span>
                        <div>
                          <strong>{person.name}</strong>
                          <span>{person.owner ? 'Owner' : 'Known person'}</span>
                        </div>
                        <output>{person.samples} samples</output>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>

            {(library?.pending ?? []).length > 0 ? (
              <div className="face-review-head">
                <div>
                  <span className="face-kicker">Review queue</span>
                  <strong>{library?.pending.length ?? 0} awaiting review</strong>
                </div>
                <p>Name a sighting to teach Marvi, or reject it without storing an identity.</p>
              </div>
            ) : null}
            <div className="face-review-grid">
              {(library?.pending ?? []).map((sighting) => (
                <article className="face-review-card" key={sighting.id}>
                  <div className="face-review-preview">
                    {sighting.image ? (
                      <img alt="An unrecognised face awaiting review" src={sighting.image} />
                    ) : (
                      <Users aria-hidden="true" />
                    )}
                    <span>
                      {sighting.at ? String(sighting.at).slice(11, 19) : `#${sighting.id}`}
                    </span>
                  </div>
                  <div className="face-review-body">
                    <div>
                      <strong>Unknown face</strong>
                      <span>
                        {typeof sighting.score === 'number'
                          ? `${Math.round(sighting.score * 100)}% nearest match`
                          : 'No reliable match'}
                      </span>
                    </div>
                    <input
                      className="control-input"
                      disabled={enrolling}
                      onChange={(event) =>
                        setVisitorNames((names) => ({
                          ...names,
                          [sighting.id]: event.target.value
                        }))
                      }
                      placeholder="Name"
                      value={visitorNames[sighting.id] ?? ''}
                    />
                    <div className="vision-review-actions">
                      <ControlButton
                        className="is-primary"
                        disabled={enrolling || !(visitorNames[sighting.id] ?? '').trim()}
                        onClick={() => void review(sighting.id, 'approve')}
                      >
                        Accept as person
                      </ControlButton>
                      <ControlButton
                        destructive
                        disabled={enrolling}
                        onClick={() => void review(sighting.id, 'reject')}
                      >
                        Reject
                      </ControlButton>
                    </div>
                  </div>
                </article>
              ))}
            </div>

            {pressed ? (
              <ControlRow description={pressed} icon={Clock3} title="Last camera action" />
            ) : null}
            {library && !library.ok ? (
              <ControlEmpty
                description={library.detail ?? 'The room is not answering.'}
                icon={ShieldAlert}
                title="Cannot read the face library"
              />
            ) : null}
          </ControlSection>

          <ControlSection icon={History} title="Recent observations">
            {visionEvents.length === 0 ? (
              <ControlEmpty
                description="Camera, presence, face, sleep, and gesture changes will appear here."
                icon={Clock3}
                title="No vision observations yet"
              />
            ) : (
              visionEvents.map((event) => (
                <ControlRow
                  action={<span className="control-time">{event.at.slice(11, 19)}</span>}
                  description={event.summary}
                  key={event.id}
                  title={event.type.replaceAll('_', ' ')}
                />
              ))
            )}
          </ControlSection>
        </>
      )}
    </ControlPage>
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
    <ControlPage
      description="ARC's observe → reflect → commit cycle and the reasoning record behind every autonomous decision."
      title="ARC Mind"
    >
      <ControlSection
        action={
          <ControlButton onClick={() => void toggle()}>
            {status?.paused ? <Play aria-hidden="true" /> : <Pause aria-hidden="true" />}
            {status?.paused ? 'Resume' : 'Pause'}
          </ControlButton>
        }
        icon={Brain}
        title="Subconscious"
      >
        <ControlRow
          action={
            <ControlPill tone={status?.paused ? 'neutral' : 'ready'}>
              {status?.paused ? 'Paused' : 'Active'}
            </ControlPill>
          }
          title="ARC cycle"
        />
        <ControlRow
          action={
            <ControlPill tone={status?.running ? 'ready' : 'neutral'}>
              {status?.running ? 'Running' : 'Stopped'}
            </ControlPill>
          }
          title="Schedule"
        />
        <ControlRow
          action={<span className="control-value">{status?.pending_events ?? 0}</span>}
          title="Pending events"
        />
        {Object.entries(status?.last_errors ?? {}).map(([job, error]) => (
          <ControlRow
            action={<ControlPill tone="danger">Error</ControlPill>}
            description={error.slice(0, 120)}
            key={job}
            title={job.replaceAll('_', ' ')}
          />
        ))}
      </ControlSection>

      <ControlSection icon={History} title="Decision history">
        {decisions.length === 0 ? (
          <ControlEmpty
            description="Decisions appear here when an event reaches the initiative policy."
            icon={Sparkles}
            title="No decisions yet"
          />
        ) : (
          decisions.map((decision) => (
            <ControlRow
              action={
                <ControlPill tone={decision.surface === 'silent' ? 'neutral' : 'accent'}>
                  {decision.surface}
                </ControlPill>
              }
              description={`${decision.at.slice(11, 19)} · ${decision.rule}${decision.detail ? ` · ${decision.detail}` : ''} · ${decision.provider} · ${decision.latency_ms.toFixed(1)} ms`}
              key={decision.id}
              title={decision.trigger.replaceAll('_', ' ')}
            />
          ))
        )}
      </ControlSection>
    </ControlPage>
  )
}

/**
 * How memory is written, and how it will be searched.
 *
 * Two settings, because two different things have to be configured for memory
 * to work at all and the answer to "why did she not remember that" is usually
 * one of them being unset. The role decides what is kept from a turn; the
 * embedding decides whether recall can match meaning rather than words.
 */
function MemorySettingsSection(): React.JSX.Element {
  const [policy, setPolicy] = useState<MemoryPolicy | null>(null)
  const [url, setUrl] = useState('')
  const [key, setKey] = useState('')
  const [model, setModel] = useState('')
  const [providerUrl, setProviderUrl] = useState('')
  const [providerKey, setProviderKey] = useState('')
  const [userId, setUserId] = useState('marvi-user')
  const [workspace, setWorkspace] = useState('marvi-os')

  useEffect(() => {
    let gone = false
    void (async () => {
      const next = await window.marvi?.getMemorySettings()
      if (gone || !next) return
      setPolicy(next)
      setUrl(next.url)
      setModel(next.model)
      setProviderUrl(next.providerUrl)
      setUserId(next.userId)
      setWorkspace(next.workspace)
    })()
    return () => {
      gone = true
    }
  }, [])

  const apply = (update: MemorySettingsUpdate): void => {
    void (async () => {
      const next = await window.marvi?.setMemorySettings(update)
      if (next) {
        setPolicy(next)
        setModel(next.model)
        setProviderUrl(next.providerUrl)
        setUserId(next.userId)
        setWorkspace(next.workspace)
      }
    })()
  }

  const source = policy?.source ?? 'off'
  const provider = policy?.provider ?? 'local'

  return (
    <ControlSection
      description="What gets kept from a conversation, and how it is found again."
      icon={Brain}
      title="How memory works"
    >
      <ControlRow
        action={
          <Picker
            options={[
              { value: 'local', label: 'Marvi local', detail: 'SQLite, on this machine' },
              { value: 'mem0', label: 'Mem0', detail: 'Pinned OSS or managed' },
              { value: 'honcho', label: 'Honcho', detail: 'Derived, traceable memory' }
            ]}
            value={provider}
            onChange={(next) => apply({ provider: next })}
            placeholder="Marvi local"
          />
        }
        description="Only one provider is active. Switching changes where new turns and recall go; it does not merge stores."
        title="Memory provider"
      />
      {provider !== 'local' ? (
        <ControlRow
          description={
            provider === 'honcho'
              ? 'Leave the endpoint blank for managed Honcho, or enter the base URL of a self-hosted server.'
              : 'Enter “local” for pinned four-operation OSS, use a self-hosted base URL, or leave blank for ADD-only Mem0 Platform.'
          }
          title={`${provider === 'honcho' ? 'Honcho' : 'Mem0'} connection`}
        >
          <form
            className="workspace-add"
            onSubmit={(event) => {
              event.preventDefault()
              apply({
                provider,
                provider_url: providerUrl,
                ...(providerKey ? { provider_key: providerKey } : {}),
                user_id: userId,
                ...(provider === 'honcho' ? { workspace } : {})
              })
              setProviderKey('')
            }}
          >
            <input
              aria-label="Memory provider endpoint"
              onChange={(event) => setProviderUrl(event.target.value)}
              placeholder={provider === 'honcho' ? 'https://api.honcho.dev' : 'managed, local, or URL'}
              value={providerUrl}
            />
            <input
              aria-label="Memory provider API key"
              onChange={(event) => setProviderKey(event.target.value)}
              placeholder={policy?.providerKeySet ? 'key saved' : 'API key'}
              type="password"
              value={providerKey}
            />
            <input
              aria-label="Memory user ID"
              onChange={(event) => setUserId(event.target.value)}
              placeholder="marvi-user"
              value={userId}
            />
            {provider === 'honcho' ? (
              <input
                aria-label="Honcho workspace"
                onChange={(event) => setWorkspace(event.target.value)}
                placeholder="marvi-os"
                value={workspace}
              />
            ) : null}
            <button className="ghost-button" type="submit">
              Save
            </button>
          </form>
        </ControlRow>
      ) : null}
      <ControlRow
        description={
          provider !== 'local'
            ? `${provider === 'honcho' ? 'Honcho' : 'Mem0'} extracts memories from completed turns.`
            : policy?.roleConfigured
            ? 'A model reads each finished exchange and decides what to keep. Chosen in Settings › Models.'
            : 'No model is set for this, so the main one does it. Choose a cheaper one in Settings › Models › Memory.'
        }
        title="Deciding what to remember"
      />
      {provider === 'local' ? <ControlRow
        action={
          <Picker
            options={[
              { value: 'off', label: 'Words only', detail: 'Keyword search. No model, no cost' },
              {
                value: 'local',
                label: 'On this machine',
                detail: '10ms a search, 23M parameters, nothing leaves'
              },
              {
                value: 'provider',
                label: 'An API',
                detail: 'Anything OpenAI-compatible, including a local server'
              }
            ]}
            value={source}
            onChange={(next) => apply({ source: next })}
            placeholder="Words only"
          />
        }
        description={
          source === 'off'
            ? 'Today “who am I” does not match “the user’s name is …”, because they share no words. An embedding fixes that.'
            : source === 'local'
              ? 'Runs on the processor, beside speech recognition. The graphics card stays free for the voice.'
              : 'Your memories are sent to whichever endpoint you name, on every recall.'
        }
        title="Searching by meaning"
      /> : null}
      {provider === 'local' && source !== 'off' ? (
        <ControlRow
          description={
            source === 'local'
              ? `Downloaded on first use. Default: ${policy?.defaultLocalModel ?? ''}`
              : 'The endpoint and model. Any server that answers POST /v1/embeddings.'
          }
          title="Model"
        >
          <form
            className="workspace-add"
            onSubmit={(event) => {
              event.preventDefault()
              apply({
                model,
                ...(source === 'provider' ? { url, ...(key ? { key } : {}) } : {})
              })
              setKey('')
            }}
          >
            <input
              aria-label="Embedding model"
              onChange={(event) => setModel(event.target.value)}
              placeholder={policy?.defaultLocalModel ?? 'model'}
              value={model}
            />
            {source === 'provider' ? (
              <>
                <input
                  aria-label="Endpoint"
                  onChange={(event) => setUrl(event.target.value)}
                  placeholder="http://127.0.0.1:11434/v1"
                  value={url}
                />
                <input
                  aria-label="API key"
                  onChange={(event) => setKey(event.target.value)}
                  placeholder={policy?.keySet ? 'key saved' : 'key, if needed'}
                  type="password"
                  value={key}
                />
              </>
            ) : null}
            <button className="ghost-button" type="submit">
              Save
            </button>
          </form>
        </ControlRow>
      ) : null}
    </ControlSection>
  )
}

function MemoryPanel(): React.JSX.Element {
  const [page, setPage] = useState<MemoryPage>({ total: 0, entries: [], summary: {} })
  const [mode, setMode] = useState<MemoryGraphMode>('tree')
  const [graph, setGraph] = useState<MemoryGraphPage>({ mode: 'tree', nodes: [], edges: [] })
  const [graphLoading, setGraphLoading] = useState(true)
  const [confirmClear, setConfirmClear] = useState(false)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let disposed = false
    const load = async (): Promise<void> => {
      const [next, nextGraph] = await Promise.all([
        window.marvi?.getMemory(),
        window.marvi?.getMemoryGraph(mode)
      ])
      if (disposed) return
      if (next) setPage(next)
      if (nextGraph) setGraph(nextGraph)
      setGraphLoading(false)
    }
    void load()
    const timer = setInterval(() => {
      if (!document.hidden) void load()
    }, 30_000)
    return () => {
      disposed = true
      clearInterval(timer)
    }
  }, [mode, reload])

  const clearAll = async (): Promise<void> => {
    await window.marvi?.clearMemory()
    setConfirmClear(false)
    setGraphLoading(true)
    setReload((n) => n + 1)
  }

  return (
    <ControlPage
      description="ARC turns observations into durable context, then keeps every source and relationship inspectable."
      title="ARC Memory"
    >
      <div className="arc-memory-workspace">
        <div className="arc-memory-toolbar">
          <div className="arc-memory-toolbar-copy">
            <strong>MEMORY GRAPH</strong>
            <small>Local-only graph projection · provenance remains attached to every node</small>
          </div>
          <div className="arc-memory-modes" aria-label="Memory graph mode">
            <button
              aria-pressed={mode === 'tree'}
              onClick={() => {
                setGraphLoading(true)
                setMode('tree')
              }}
              type="button"
            >
              TREE
            </button>
            <button
              aria-pressed={mode === 'contacts'}
              onClick={() => {
                setGraphLoading(true)
                setMode('contacts')
              }}
              type="button"
            >
              CONNECTIONS
            </button>
          </div>
        </div>
        <ArcMemoryGraph graph={graph} loading={graphLoading} />
      </div>

      <ControlSection
        action={
          confirmClear ? (
            <div className="control-actions">
              <ControlButton destructive onClick={() => void clearAll()}>
                <Trash2 aria-hidden="true" /> Delete everything
              </ControlButton>
              <ControlButton onClick={() => setConfirmClear(false)}>Cancel</ControlButton>
            </div>
          ) : (
            <ControlButton destructive onClick={() => setConfirmClear(true)}>
              <Trash2 aria-hidden="true" /> Forget everything
            </ControlButton>
          )
        }
        icon={Database}
        title="Local store"
      >
        <ControlRow action={<span className="control-value">{page.total}</span>} title="Entries" />
        <ControlRow
          action={
            <span className="control-value">
              {(page.summary.facts ?? []).join(' · ') || 'None'}
            </span>
          }
          title="Known facts"
        />
        <ControlRow
          action={
            <span className="control-value">
              {page.summary.graph?.entities ?? 0} / {page.summary.graph?.relations ?? 0}
            </span>
          }
          description="Entities / explicit relationships"
          title="Knowledge graph"
        />
      </ControlSection>

      <MemoryList entries={page.entries} />
    </ControlPage>
  )
}

/**
 * Everything about memory that is a setting rather than a picture.
 *
 * Split off the graph page because the two answer different questions. The
 * graph is something you look at; this is something you change, and having
 * both on one page meant scrolling past a canvas to reach a dropdown.
 *
 * Tabs rather than sections stacked down the page: there are three unrelated
 * subjects here and only one of them is ever the reason somebody came.
 */
const MEMORY_TABS = ['How it works', 'What is remembered', 'Import'] as const

function MemorySettingsPanel(): React.JSX.Element {
  const [tab, setTab] = useState<(typeof MEMORY_TABS)[number]>('How it works')
  const [page, setPage] = useState<MemoryPage>({ total: 0, entries: [], summary: {} })

  useEffect(() => {
    let gone = false
    void (async () => {
      const next = await window.marvi?.getMemory()
      if (!gone && next) setPage(next)
    })()
    return () => {
      gone = true
    }
  }, [tab])

  return (
    <ControlPage
      className="settings-page"
      description="What Marvi keeps from a conversation, how she finds it again, and what she already knows."
      title="Memory"
    >
      <div className="arc-memory-modes" aria-label="Memory settings">
        {MEMORY_TABS.map((name) => (
          <button
            aria-pressed={tab === name}
            key={name}
            onClick={() => setTab(name)}
            type="button"
          >
            {name.toUpperCase()}
          </button>
        ))}
      </div>

      {tab === 'How it works' ? <MemorySettingsSection /> : null}
      {tab === 'What is remembered' ? (
        <>
          <ControlSection icon={Database} title="Local store">
            <ControlRow
              action={<span className="control-value">{page.total}</span>}
              title="Entries"
            />
            <ControlRow
              action={
                <span className="control-value">
                  {page.summary.graph?.entities ?? 0} / {page.summary.graph?.relations ?? 0}
                </span>
              }
              description="Entities / relationships. Filled by dreaming, not by hand."
              title="Knowledge graph"
            />
          </ControlSection>
          <MemoryList entries={page.entries} />
        </>
      ) : null}
      {tab === 'Import' ? <MemoryImportSection /> : null}
    </ControlPage>
  )
}

/**
 * Bringing memories in from another assistant.
 *
 * Three shapes, because assistants differ in what they can give you:
 *
 * * **A chat assistant** — ChatGPT, Claude, Gemini, Grok — cannot export, but
 *   it can be asked. The prompt below is copied into that chat; what comes
 *   back is a file, and the file goes through the same pipeline as everything
 *   else. The prompt is served by the Gateway rather than written here, so the
 *   format it asks for and the parser that reads it cannot drift apart.
 * * **An agent that keeps files** — hermes, OpenClaw — hands over `MEMORY.md`
 *   directly.
 * * **A memory service** — Honcho, Mem0 — is read over its API.
 *
 * Two steps in every case. Picking the wrong file fails silently — a config
 * file reads as empty and an import would report success — so what was found
 * is shown first, along with anything the credential gate will refuse.
 */
const IMPORT_SOURCES = [
  {
    key: 'chat',
    label: 'A chat assistant',
    detail: 'ChatGPT, Claude, Gemini, Grok — copy a prompt, save the reply'
  },
  { key: 'file', label: 'A memory file', detail: 'MEMORY.md or USER.md from hermes or OpenClaw' },
  { key: 'honcho', label: 'Honcho', detail: 'Read from your account' },
  { key: 'mem0', label: 'Mem0', detail: 'Read from your account' }
] as const

function MemoryImportSection(): React.JSX.Element {
  const [kind, setKind] = useState<(typeof IMPORT_SOURCES)[number]['key']>('chat')
  const [sources, setSources] = useState<MemoryImportSources | null>(null)
  const [workspaces, setWorkspaces] = useState<string[]>([])
  const [scope, setScope] = useState('')
  const [request, setRequest] = useState<MemoryImportRequest | null>(null)
  const [found, setFound] = useState<MemoryImportPreview | null>(null)
  const [result, setResult] = useState<MemoryImportResult | null>(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState('')

  useEffect(() => {
    let gone = false
    void (async () => {
      const next = await window.marvi?.getImportSources()
      if (!gone) setSources(next ?? null)
    })()
    return () => {
      gone = true
    }
  }, [])

  // Asked rather than assumed: on a real account the default workspace was
  // empty and everything was in one named after the assistant that wrote it.
  useEffect(() => {
    if (kind !== 'honcho') return
    let gone = false
    void (async () => {
      const next = await window.marvi?.getHonchoWorkspaces()
      if (gone) return
      setWorkspaces(next?.workspaces ?? [])
      setScope((current) => current || next?.workspaces?.[0] || '')
    })()
    return () => {
      gone = true
    }
  }, [kind])

  const look = async (next: MemoryImportRequest): Promise<void> => {
    setRequest(next)
    setResult(null)
    setBusy('reading')
    try {
      setFound((await window.marvi?.previewMemoryImport(next)) ?? null)
    } finally {
      setBusy('')
    }
  }

  const chooseFiles = async (): Promise<void> => {
    const chosen = (await window.marvi?.chooseMemoryFiles()) ?? []
    if (chosen.length > 0) await look({ paths: chosen })
  }

  const run = async (): Promise<void> => {
    if (!request) return
    setBusy('importing')
    try {
      setResult((await window.marvi?.importMemories(request)) ?? null)
      setFound(null)
      setRequest(null)
    } finally {
      setBusy('')
    }
  }

  const reachable = kind === 'honcho' ? sources?.honcho : kind === 'mem0' ? sources?.mem0 : true

  return (
    <>
      <ControlSection
        description="Marvi rewrites each memory to fit rather than pasting it in, leaves out what she already knows, and refuses anything that looks like a credential."
        icon={Database}
        title="Import from another assistant"
      >
        <Picker
          options={IMPORT_SOURCES.map((source) => ({
            value: source.key,
            label: source.label,
            detail: source.detail
          }))}
          value={kind}
          onChange={(next) => {
            setKind(next as typeof kind)
            setFound(null)
            setResult(null)
            setRequest(null)
          }}
          placeholder="Where from"
        />

        {kind === 'chat' && sources ? (
          <>
            <ControlRow
              action={
                <ControlButton
                  onClick={() => {
                    void navigator.clipboard.writeText(sources.packPrompt)
                    setCopied(true)
                    window.setTimeout(() => setCopied(false), 2000)
                  }}
                >
                  {copied ? 'Copied' : 'Copy the prompt'}
                </ControlButton>
              }
              description="Paste it into ChatGPT, Claude, Gemini or Grok, save the JSON it replies with, then choose that file below."
              title="Ask it to write down everything it knows"
            />
            <pre className="service-output skill-body">{sources.packPrompt}</pre>
          </>
        ) : null}

        {kind === 'honcho' ? (
          workspaces.length > 0 ? (
            <Picker
              options={workspaces.map((name) => ({ value: name, label: name, detail: '' }))}
              value={scope}
              onChange={setScope}
              placeholder="Workspace"
            />
          ) : (
            <p className="notice">
              {reachable
                ? 'Looking for your workspaces…'
                : 'No Honcho key found. Set HONCHO_API_KEY, or choose Honcho as your memory provider and give it a key.'}
            </p>
          )
        ) : null}

        {kind === 'mem0' && !reachable ? (
          <p className="notice">
            No Mem0 key found. Set MEM0_API_KEY, or choose Mem0 as your memory provider.
          </p>
        ) : null}

        <div className="provider-actions">
          {kind === 'honcho' || kind === 'mem0' ? (
            <ControlButton
              disabled={!!busy || !reachable || (kind === 'honcho' && !scope)}
              onClick={() => void look({ provider: kind, scope })}
            >
              {busy === 'reading' ? 'Reading' : 'Look at what is there'}
            </ControlButton>
          ) : (
            <ControlButton disabled={!!busy} onClick={() => void chooseFiles()}>
              {busy === 'reading' ? 'Reading' : 'Choose files'}
            </ControlButton>
          )}
        </div>
      </ControlSection>

      {found ? (
        <ControlSection icon={Database} title="Before importing">
          <ControlRow
            action={<span className="control-value">{found.found}</span>}
            description={found.files.map((file) => `${file.name} (${file.found})`).join(' · ')}
            title="Memories found"
          />
          {found.refused.length > 0 ? (
            <ControlRow
              action={<span className="control-value">{found.refused.length}</span>}
              description={`Left out. An assistant that is told a password writes it down like anything else, and these carry one — ${found.refused
                .slice(0, 3)
                .map((row) => row.quote.slice(0, 56))
                .join(' · ')}`}
              icon={ShieldAlert}
              title="Refused as credentials"
            />
          ) : null}
          {found.sample.length > 0 ? (
            <pre className="service-output skill-body">{found.sample.join('\n')}</pre>
          ) : null}
          <div className="provider-actions">
            <ControlButton disabled={found.found === 0 || !!busy} onClick={() => void run()}>
              {busy === 'importing' ? 'Importing' : `Import ${found.found - found.refused.length}`}
            </ControlButton>
            <ControlButton
              onClick={() => {
                setFound(null)
                setRequest(null)
              }}
            >
              Cancel
            </ControlButton>
          </div>
          {busy === 'importing' ? (
            <p className="notice">
              A model is rewriting each one to fit Marvi, then dreaming over the result to draw the
              relations between them. Hundreds of memories take a few minutes.
            </p>
          ) : null}
        </ControlSection>
      ) : null}

      {result ? (
        <ControlSection icon={result.imported > 0 ? Database : ShieldAlert} title="Imported">
          <ControlRow
            description={
              result.imported > 0
                ? `${result.imported} of ${result.found} kept${
                    result.dreamt?.linked
                      ? `, and ${result.dreamt.linked} relationship${
                          result.dreamt.linked === 1 ? '' : 's'
                        } drawn between them`
                      : ''
                  }. The rest were duplicates of what she already knew, or not about you.`
                : result.detail || 'Nothing in that looked like a memory.'
            }
            title={result.imported > 0 ? 'Done' : 'Nothing imported'}
          />
          {result.refused && result.refused.length > 0 ? (
            <ControlRow
              action={<span className="control-value">{result.refused.length}</span>}
              description="Left out because they carried a password, key or identity number."
              icon={ShieldAlert}
              title="Refused"
            />
          ) : null}
        </ControlSection>
      ) : null}
    </>
  )
}

/** What is remembered, newest first. Shared by the graph page and Settings. */
function MemoryList({ entries }: { entries: MemoryEntry[] }): React.JSX.Element {
  return (
    <ControlSection icon={History} title="Stored memories">
      {entries.length === 0 ? (
        <ControlEmpty
          description="Useful preferences and facts will appear after Marvi has something worth retaining."
          icon={Database}
          title="Nothing remembered yet"
        />
      ) : (
        entries.map((entry) => (
          <ControlRow
            action={
              <ControlPill
                tone={entry.source === 'dreaming' ? 'neutral' : entry.trusted ? 'neutral' : 'danger'}
              >
                {/* Something Marvi worked out is neither a fact she was told
                    nor content from outside, and calling it "Untrusted"
                    alongside an imported email said the wrong thing about
                    both. */}
                {entry.source === 'dreaming'
                  ? 'Worked out'
                  : entry.trusted
                    ? entry.kind
                    : 'From outside'}
              </ControlPill>
            }
            description={`${entry.at.slice(0, 10)} · ${entry.source}`}
            key={entry.id}
            title={entry.subject}
          />
        ))
      )}
    </ControlSection>
  )
}

function AccountsPanel(): React.JSX.Element {
  const [page, setPage] = useState<AccountPage | null>(null)
  const [catalog, setCatalog] = useState<AccountToolkit[]>([])
  const [loaded, setLoaded] = useState(false)
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState('')
  const [deleteArmed, setDeleteArmed] = useState('')
  const [projectKey, setProjectKey] = useState('')

  const load = useCallback(async (): Promise<void> => {
    const next = await window.marvi?.getAccounts()
    if (!next) return
    setPage(next)
    setLoaded(true)
    if (next.available && catalog.length === 0) {
      setCatalog((await window.marvi?.getAccountCatalog()) ?? [])
    }
  }, [catalog.length])

  useEffect(() => {
    let disposed = false
    const update = async (): Promise<void> => {
      if (!disposed) await load()
    }
    void update()
    const timer = setInterval(() => void update(), 10_000)
    return () => {
      disposed = true
      clearInterval(timer)
    }
  }, [load])

  const act = useCallback(
    async (
      key: string,
      work: () => Promise<boolean | { ok: boolean; detail: string }>
    ): Promise<void> => {
      setBusy(key)
      setNotice('')
      const result = await work()
      const ok = typeof result === 'boolean' ? result : result.ok
      setNotice(
        typeof result === 'boolean'
          ? ok
            ? 'Account settings updated.'
            : 'The account service refused that change.'
          : result.detail
      )
      setBusy('')
      if (ok) await load()
    },
    [load]
  )

  const accounts = page?.accounts ?? []
  const available = page?.available ?? true
  const existing = new Set(accounts.map((row) => row.toolkit))
  const priority = ['gmail', 'googlecalendar', 'slack', 'notion', 'github', 'googledrive']
  const connectable = catalog
    .filter((row) => !existing.has(row.slug))
    .filter((row) => {
      const needle = query.trim().toLowerCase()
      return !needle || `${row.name} ${row.slug} ${row.description}`.toLowerCase().includes(needle)
    })
    .sort((a, b) => {
      const ai = priority.indexOf(a.slug)
      const bi = priority.indexOf(b.slug)
      if (ai !== -1 || bi !== -1) return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi)
      return a.name.localeCompare(b.name)
    })
    .slice(0, query ? 20 : 6)

  const syncFor = (
    account: ConnectedAccount
  ): AccountPage['sync']['connections'][number] | undefined =>
    page?.sync.connections.find(
      (row) => row.toolkit === account.toolkit && (!account.id || row.connectionId === account.id)
    )

  return (
    <ControlPage
      className="accounts-page"
      description="Connect services, set ARC's authority, and control what enters memory."
      title="Accounts"
    >
      <ControlSection
        action={
          <ControlPill tone={page?.triggers.connected ? 'ready' : 'neutral'}>
            {page?.triggers.connected ? 'LIVE EVENTS' : 'POLLING'}
          </ControlPill>
        }
        description="OAuth stays with Composio; credentials never enter Marvi OS."
        icon={Users}
        title="Connected accounts"
      >
        {!loaded ? (
          <ProcessingCard compact detail="Checking connected accounts." title="Loading accounts" />
        ) : accounts.length === 0 ? (
          <ControlEmpty
            description={
              available
                ? 'Choose a service below. Every new connection starts read-only.'
                : 'Configure the account service before connecting an account.'
            }
            icon={Users}
            title="No accounts connected"
          />
        ) : (
          <>
            <ControlRow
              action={
                <ControlPill tone={available ? 'ready' : 'warning'}>
                  {available ? page?.detail : 'Not configured'}
                </ControlPill>
              }
              title="Account service"
            />
            {accounts.map((account) => {
              const sync = syncFor(account)
              const key = account.id || account.toolkit
              const label =
                catalog.find((row) => row.slug === account.toolkit)?.name ?? account.toolkit
              return (
                <ControlRow
                  action={
                    <div className="account-row-controls">
                      <div
                        aria-label={`${label} capability`}
                        className="account-scope"
                        role="group"
                      >
                        {(['read', 'write', 'admin'] as const).map((scope) => (
                          <button
                            aria-pressed={account.scope === scope}
                            disabled={busy === key}
                            key={scope}
                            onClick={() =>
                              void act(key, () =>
                                window.marvi!.setAccountPolicy(account.toolkit, { scope })
                              )
                            }
                            type="button"
                          >
                            {scope}
                          </button>
                        ))}
                      </div>
                      <div className="account-actions">
                        <ControlButton
                          disabled={busy === key || !account.connected}
                          onClick={() =>
                            void act(key, () =>
                              window.marvi!.syncAccount(account.toolkit, account.id)
                            )
                          }
                          title="Fetch new memory now"
                        >
                          <RefreshCw aria-hidden="true" /> Sync
                        </ControlButton>
                        {account.needsReconnect ? (
                          <ControlButton
                            disabled={busy === key}
                            onClick={() =>
                              void act(key, () => window.marvi!.refreshAccount(account.id))
                            }
                          >
                            <Link2 aria-hidden="true" /> Reconnect
                          </ControlButton>
                        ) : (
                          <ControlButton
                            disabled={busy === key || !account.id}
                            onClick={() =>
                              void act(key, () =>
                                window.marvi!.setAccountEnabled(account.id, !account.connected)
                              )
                            }
                          >
                            <Unplug aria-hidden="true" /> {account.connected ? 'Disable' : 'Enable'}
                          </ControlButton>
                        )}
                        <ControlButton
                          destructive={deleteArmed === key}
                          disabled={busy === key || !account.id}
                          onClick={() => {
                            if (deleteArmed !== key) {
                              setDeleteArmed(key)
                              setNotice(`Press Remove again to revoke ${label}.`)
                              return
                            }
                            setDeleteArmed('')
                            void act(key, () => window.marvi!.deleteAccount(account.id))
                          }}
                        >
                          <Trash2 aria-hidden="true" />{' '}
                          {deleteArmed === key ? 'Confirm remove' : 'Remove'}
                        </ControlButton>
                      </div>
                    </div>
                  }
                  description={
                    <span className="account-health-line">
                      <ControlPill tone={account.connected ? 'ready' : 'danger'}>
                        {account.connected ? 'CONNECTED' : account.status.toUpperCase()}
                      </ControlPill>
                      <span>
                        {account.syncEnabled ? 'Memory on' : 'Memory off'} ·{' '}
                        {sync?.lastSuccessAt
                          ? `last sync ${new Date(sync.lastSuccessAt).toLocaleString()}`
                          : 'not synced yet'}
                        {sync?.lastError ? ` · ${sync.lastError}` : ''}
                      </span>
                    </span>
                  }
                  key={key}
                  title={label}
                >
                  <button
                    aria-pressed={account.syncEnabled}
                    className="account-memory-toggle"
                    disabled={busy === key}
                    onClick={() =>
                      void act(key, () =>
                        window.marvi!.setAccountPolicy(account.toolkit, {
                          sync_enabled: !account.syncEnabled
                        })
                      )
                    }
                    type="button"
                  >
                    {account.syncEnabled ? 'Stop memory auto-fetch' : 'Enable memory auto-fetch'}
                  </button>
                </ControlRow>
              )
            })}
          </>
        )}
      </ControlSection>

      {!available && loaded ? (
        <ControlSection
          description="One Marvi project key enables hosted OAuth. Connected-service passwords and tokens never enter Marvi OS."
          icon={Link2}
          title="Connect Composio"
        >
          <div className="account-configure">
            <label htmlFor="composio-project-key">Project API key</label>
            <input
              autoComplete="off"
              id="composio-project-key"
              onChange={(event) => setProjectKey(event.target.value)}
              placeholder="Paste a Composio project key"
              type="password"
              value={projectKey}
            />
            <ControlButton
              disabled={busy === 'configure' || projectKey.trim().length < 8}
              onClick={() =>
                void act('configure', async () => {
                  const result = await window.marvi!.configureAccounts(projectKey)
                  if (result.ok) setProjectKey('')
                  return result
                })
              }
            >
              <Link2 aria-hidden="true" /> Connect account service
            </ControlButton>
          </div>
        </ControlSection>
      ) : null}

      {available ? (
        <ControlSection
          description="The first six have native ARC memory providers; every connected service gets dynamic tools."
          icon={Link2}
          title="Connect a service"
        >
          <div className="account-catalog-search">
            <label htmlFor="account-search">Find a toolkit</label>
            <input
              id="account-search"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Slack, GitHub, Drive…"
              type="search"
              value={query}
            />
          </div>
          {connectable.length ? (
            connectable.map((toolkit) => (
              <ControlRow
                action={
                  <ControlButton
                    disabled={busy === `connect:${toolkit.slug}`}
                    onClick={() =>
                      void act(`connect:${toolkit.slug}`, () =>
                        window.marvi!.connectAccount(toolkit.slug)
                      )
                    }
                  >
                    <Link2 aria-hidden="true" /> Connect
                  </ControlButton>
                }
                description={toolkit.description || `Connect ${toolkit.name} through Composio.`}
                key={toolkit.slug}
                title={
                  <span className="account-catalog-title">
                    {toolkit.name}
                    {toolkit.nativeMemory ? (
                      <ControlPill tone="accent">ARC MEMORY</ControlPill>
                    ) : null}
                  </span>
                }
              />
            ))
          ) : (
            <ControlEmpty
              description={
                query ? 'Try a broader service name.' : 'Every listed service is connected.'
              }
              icon={Link2}
              title={query ? 'No matching toolkit' : 'Catalog connected'}
            />
          )}
        </ControlSection>
      ) : null}

      {notice ? (
        <p aria-live="polite" className="account-notice">
          {notice}
        </p>
      ) : null}
    </ControlPage>
  )
}

const ACCESS_LABEL: Record<string, string> = {
  api: 'Pay as you go',
  plan: 'Subscription plan',
  local: 'Local'
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

  // A local provider is connected only once it has answered with a model
  // list. It used to count the moment it had a default URL -- which every one
  // of them ships with -- so LM Studio and Ollama read CONNECTED on a machine
  // where neither was running, won the fallback, and answered turns with
  // nothing behind them.
  const offline = provider.reachable === false
  const ready = provider.configured && !offline

  return (
    <div className="service-row provider-row">
      <span className="service-name">{provider.label}</span>
      <span className={`service-state state-${ready ? 'ready' : 'pending'}`}>
        {provider.cooldown
          ? `COOLING DOWN ${Math.round(provider.cooldown.seconds_remaining)}S`
          : offline
            ? 'Not running'
            : oauth
              ? oauth.state.toUpperCase()
              : provider.configured
                ? 'Connected'
                : 'Not connected'}
      </span>
      {offline ? (
        <small className="provider-cooldown">
          Nothing is listening on {provider.baseUrl} — start it, or point{' '}
          {provider.env.url || 'the URL'} somewhere else.
        </small>
      ) : null}
      {provider.accessPath === 'local' && !provider.configured ? (
        <LocalConnect name={provider.name} label={provider.label} onDone={onRefresh} />
      ) : null}
      <small>
        {ACCESS_LABEL[provider.accessPath]} · {provider.apiMode.replace(/_/g, ' ')} ·{' '}
        {provider.models.main || 'no model'}
      </small>
      {provider.cooldown ? (
        <small className="provider-cooldown">{provider.cooldown.reason}</small>
      ) : null}

      {provider.limits.windows.length > 0 ? (
        <small>
          Limits {provider.limits.windows.map(([win, cap]) => `${cap} / ${win}`).join(', ')}
          {provider.limits.readable ? '' : ' (not published over the API)'}
        </small>
      ) : null}

      <button className="phase" type="button" onClick={() => setOpen(!open)}>
        {open ? 'Close' : provider.configured ? 'Edit' : 'Connect'}
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
                    ? 'Read the warning first'
                    : signIn === 'waiting'
                      ? 'Waiting for sign-in'
                      : oauth.connected
                        ? 'Sign in again'
                        : 'Sign in'}
                </button>
                {oauth.connected ? (
                  <button
                    className="phase danger"
                    type="button"
                    disabled={busy}
                    onClick={() => void disconnect()}
                  >
                    Disconnect
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
              {blocked ? 'Read the warning first' : busy ? 'Saving' : 'Save'}
            </button>
            {provider.configured && needsKey ? (
              <button
                className="phase danger"
                type="button"
                disabled={busy}
                onClick={() => void save({ [keyEnv]: '' })}
              >
                Disconnect
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
    ['Local', 'local'],
    ['Pay as you go', 'api'],
    ['Subscription plans', 'plan']
  ]

  return (
    <ControlPage
      description="Connect a model service and choose where each request runs."
      title="Providers"
    >
      {!page && !error ? (
        <ProcessingCard
          compact
          detail="Checking configured endpoints and connection state."
          title="Loading providers"
        />
      ) : null}
      {error ? <p className="notice notice-warn">{error}</p> : null}

      {groups.map(([label, path]) => {
        const rows = (page?.providers ?? []).filter((row) => row.accessPath === path)
        if (rows.length === 0) return null
        return (
          <ControlSection icon={path === 'local' ? Server : Wifi} key={path} title={label}>
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
          </ControlSection>
        )
      })}
    </ControlPage>
  )
}

/**
 * Connect a local provider by asking it for its models.
 *
 * A base URL is not evidence that anything is there. The only proof that
 * matters is a model list coming back, so that is what the button waits for --
 * and a provider that does not answer stays disconnected and says why.
 */
function LocalConnect({
  name,
  label,
  onDone
}: {
  name: string
  label: string
  onDone: () => void
}): React.JSX.Element {
  const [busy, setBusy] = useState(false)
  const [detail, setDetail] = useState('')

  const connect = async (): Promise<void> => {
    setBusy(true)
    setDetail('')
    const result = await window.marvi?.connectLocal(name)
    setBusy(false)
    if (result?.connected) {
      setDetail(`${label} answered with ${result.models} models.`)
      onDone()
      return
    }
    setDetail(result?.detail || `${label} did not answer.`)
  }

  return (
    <div className="provider-connect">
      <button className="phase" disabled={busy} onClick={() => void connect()} type="button">
        {busy ? 'ASKING…' : 'CONNECT'}
      </button>
      {detail ? <small className="provider-cooldown">{detail}</small> : null}
    </div>
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
    <ControlPage
      description="Edit Marvi's identity and your standing preferences."
      title="Identity"
    >
      <ControlSection
        action={
          <ControlButton disabled={saved} onClick={() => void save()}>
            {saved ? <CheckCircle2 aria-hidden="true" /> : null}
            {saved ? 'Saved' : 'Save changes'}
          </ControlButton>
        }
        icon={Sparkles}
        title="Identity files"
      >
        {identity ? (
          <ControlRow
            action={
              <span className="control-value">
                {identity.tokens} / {identity.budget} tokens
                {identity.truncated ? ' · Truncated' : ''}
              </span>
            }
            description={identity.directory}
            title="Prompt budget"
          />
        ) : null}
        <label className="control-editor">
          <span>Soul</span>
          <small>Voice, temperament, and refusals</small>
          <textarea
            rows={10}
            value={soul}
            onChange={(event) => {
              setSoul(event.target.value)
              setSaved(false)
            }}
          />
        </label>
        <label className="control-editor">
          <span>User</span>
          <small>Name, hours, and standing preferences</small>
          <textarea
            rows={10}
            value={user}
            onChange={(event) => {
              setUser(event.target.value)
              setSaved(false)
            }}
          />
        </label>
      </ControlSection>
    </ControlPage>
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
  const sessionMetrics = useStore($sessionMetrics)
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
  // The worker is loading its speech models. Shown wherever the eye lands,
  // because a session joined during it looks identical to a working one.
  const warming = voiceComponent?.state === 'starting'

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
    <section className="voice-page">
      <div className="voice-orb-surface">
        <VoiceOrb active={speaking || listening} level={voice.level} phase={voice.phase} />
        {/* One stack, positioned once.
         *
         * The orb's canvas fills the surface, so anything after it in normal
         * flow lands below the bottom edge — outside the field entirely, which
         * is where the question and the secret field were appearing. The
         * subtitles escaped that by positioning themselves, and copying that
         * trick per card is how three things end up overlapping each other.
         * They share a container instead. */}
        <div className="voice-stack">
          <Subtitles />
          <AskedQuestion />
          <SecretField />
        </div>
      </div>

      {/* Top-left: what Marvi is doing, and what is stopping it. */}
      <div className="voice-hud voice-hud-state">
        {/* Not joined is its own state, and saying READY for it was a lie: the
            page claimed Marvi was listening while nothing was in the room. */}
        <span
          className={`voice-hud-phase phase-${
            warming ? 'starting' : link === 'live' ? mood : 'idle'
          }`}
        >
          {warming
            ? 'WARMING UP'
            : link === 'live'
              ? voice.phase.toUpperCase()
              : link === 'connecting'
                ? 'JOINING'
                : 'IDLE'}
        </span>
        {/* Said here as well as on the button, because this is where the eye
            is. Joining before the models finish loading produced a session
            that showed LISTENING and heard nothing -- you could talk into it
            for as long as you liked. */}
        <strong>
          {warming
            ? 'Loading the speech models — she cannot hear you yet'
            : link === 'live'
              ? voice.caption
              : 'Press Join to start listening'}
        </strong>
        <WakeIndicator />
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
          {/* The voice, chosen here rather than three clicks away in Settings.
              It is the one thing about speech output anybody changes, and the
              page where you hear it is the page to change it on. */}
          <dt>SPEECH OUT</dt>
          <dd>
            <VoicePicker />
          </dd>
        </div>
        <div>
          <dt>MIC</dt>
          <dd>{deviceError ? 'unavailable' : microphoneLabel(devices)}</dd>
        </div>
      </dl>

      <MessageTiming
        aria-label="Voice session metrics"
        className="voice-session-timing"
        stats={sessionTimingStats(sessionMetrics)}
        streaming={speaking || listening}
      />

      <ConversationBar level={voice.level} warming={warming} />
    </section>
  )
}

/**
 * Whether Marvi is listening for her name, and when she last heard it.
 *
 * The gate had no surface at all before this: no way to see that the model had
 * loaded, and nothing when it fired. A gate silently not running looked
 * exactly like one running and never triggering — both are Marvi ignoring you.
 */
function useWake(pollMs: number): WakeStatus | null {
  const [wake, setWake] = useState<WakeStatus | null>(null)

  useEffect(() => {
    let gone = false
    const read = async (): Promise<void> => {
      const next = await window.marvi?.getWake()
      if (!gone) setWake(next ?? null)
    }
    void read()
    const timer = setInterval(() => void read(), pollMs)
    return () => {
      gone = true
      clearInterval(timer)
    }
  }, [pollMs])

  return wake
}

/**
 * What the wake word is doing, in three words, in the status bar.
 *
 * Three states rather than a light that is on or off, because the one worth
 * seeing is the middle one. ON means it will start at your next login. LIVE
 * means it is holding the microphone right now. A listener registered but not
 * running is the failure that used to be invisible — she simply never answered
 * and nothing anywhere said why.
 */
function WakeStatusItem({ onOpen }: { onOpen: () => void }): React.JSX.Element | null {
  const wake = useWake(3000)
  if (!wake) return null

  const { autostart, running } = wake.listener
  const heard = wake.recentlyHeard
  // Registered and silent for a while is stopped, not starting. It said
  // STARTING for thirty hours straight, which is a status bar lying rather
  // than reporting.
  const stopped = autostart && !running && (wake.listener.silentFor ?? 0) > 60
  const label = heard
    ? 'HEARD'
    : running
      ? 'LIVE'
      : stopped
        ? 'STOPPED'
        : autostart
          ? 'STARTING'
          : 'OFF'
  const tooltip = heard
    ? `Heard her name at ${Math.round(wake.confidence * 100)}% confidence`
    : running
      ? 'Listening for “Marvi” — say it to join hands-free'
      : autostart
        ? stopped
          ? `Registered, but it has not been heard from for ${sinceWhen(wake.listener.silentFor)}`
          : 'Registered to start at login, and coming up'
        : 'Not listening. Turn it on in Voice settings.'

  return (
    <UiTooltip label={tooltip} side="top">
      <button
        className={`status-item${heard ? ' status-yolo' : ''}`}
        onClick={onOpen}
        type="button"
      >
        <Mic aria-hidden="true" />
        <span>Wake</span>
        <span className="status-detail">{label.toLowerCase()}</span>
      </button>
    </UiTooltip>
  )
}

function WakeIndicator(): React.JSX.Element | null {
  // Polled quickly, because the whole point is to acknowledge a detection
  // while the person who spoke is still waiting to see whether it landed.
  const wake = useWake(1500)
  if (!wake) return null

  if (!wake.modelPresent) {
    return <p className="voice-hud-blocker">Wake word model missing — press Join instead</p>
  }
  if (!wake.listener.autostart) return null

  return (
    <span className={`wake-chip${wake.recentlyHeard ? ' is-heard' : ''}`}>
      {wake.recentlyHeard
        ? `Heard you — ${Math.round(wake.confidence * 100)}%`
        : wake.listener.running
          ? 'Listening for “Marvi”'
          : 'Wake word not running'}
    </span>
  )
}

/**
 * The wake word switch, which now controls the thing it says it does.
 *
 * It used to set `MARVI_WAKE_WORD`, an environment variable read by a gate
 * inside the voice session — so it only ever decided which of the turns you
 * had already joined for counted, and did nothing at all when Marvi was
 * closed. The switch now registers the standalone listener to start at login,
 * which is the only arrangement in which a wake word means anything.
 */
/** "two minutes", "30 hours" — enough to tell a hiccup from a death. */
function sinceWhen(seconds: number | null): string {
  if (seconds === null) return 'never'
  if (seconds < 90) return `${Math.round(seconds)} seconds`
  if (seconds < 5400) return `${Math.round(seconds / 60)} minutes`
  if (seconds < 172800) return `${Math.round(seconds / 3600)} hours`
  return `${Math.round(seconds / 86400)} days`
}

function WakeSettings(): React.JSX.Element {
  const wake = useWake(4000)
  // Held locally so the switch moves on the click rather than on the next
  // poll. Turning it on shells out to the registry and can take a moment.
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState<boolean | null>(null)

  if (!wake) return <span className="construction">UNAVAILABLE</span>

  const set = (values: Record<string, string>): void => {
    void window.marvi?.setProviderSettings(values)
  }

  const on = pending ?? wake.listener.autostart
  const toggle = async (want?: boolean): Promise<void> => {
    const target = want ?? !on
    setBusy(true)
    setPending(target)
    try {
      // Enabling stops whatever is already running before starting, so asking
      // for `true` while it is already registered is a restart.
      const next = await window.marvi?.setWakeAutostart(target, wake.device)
      setPending(next?.autostart ?? target)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="voice-choice">
      <button
        aria-checked={on}
        className={on ? 'mode-switch active' : 'mode-switch'}
        disabled={busy}
        onClick={() => void toggle()}
        role="switch"
        type="button"
      >
        {on ? 'LISTENING FOR “MARVI”' : 'OFF — PRESS JOIN'}
      </button>

      {on ? (
        <>
          <Picker
            options={[
              {
                value: '0.35',
                label: 'Sensitive',
                detail: 'Catches you sooner, false alarms more likely'
              },
              { value: '0.5', label: 'Balanced', detail: 'The default' },
              {
                value: '0.7',
                label: 'Strict',
                detail: 'Say it clearly; almost never fires by accident'
              }
            ]}
            value={String(wake.threshold)}
            onChange={(next) => set({ [wake.thresholdSetting]: next })}
            placeholder="Balanced"
          />
          {!wake.listener.running && wake.listener.everRan ? (
            <ControlRow
              action={
                <button
                  className="ghost-button"
                  disabled={busy}
                  onClick={() => void toggle(true)}
                  type="button"
                >
                  START IT
                </button>
              }
              description={`It last reported ${sinceWhen(
                wake.listener.silentFor
              )} ago and has not since. Starting it re-registers the listener and launches it now, rather than waiting for the next login.`}
              icon={ShieldAlert}
              title="The listener has stopped"
            />
          ) : null}
          <p className="notice">
            {wake.device
              ? `Listening on ${wake.device}. `
              : 'Listening on the system default microphone. '}
            Right-click Marvi&rsquo;s tray icon to change it &mdash; the listener is the thing
            that opens the microphone, so it is the only one that knows which ones it can open.
          </p>
          <p className="notice">
            {!wake.modelPresent
              ? 'No wake word model found, so there is nothing to listen with.'
              : wake.listener.running
                ? 'Running now, and at every login. Saying “Marvi” joins the same way pressing Join does — and opens Marvi first if she is closed.'
                : wake.listener.error ||
                  (wake.listener.everRan
                    ? ''
                    : 'Registered to start at login. It has not started yet; give it a moment.')}
          </p>
        </>
      ) : null}
    </div>
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

  // An empty list used to mean "the multi-gigabyte voice download has not
  // finished". It cannot mean that any more -- the voices are part of an 82M
  // checkpoint -- so an empty list now means the Gateway did not answer.
  if (page && page.voices.length === 0) {
    return <span className="construction">VOICES UNAVAILABLE — THE GATEWAY DID NOT ANSWER.</span>
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
        empty="No voices available."
      />
      {page?.missing ? (
        // Almost always a speaker name left over from the previous engine.
        // Saying "not installed" would send someone to the installer for a
        // file that no longer exists in any version.
        <span className="construction">
          {`"${page.selected}" IS NOT ONE OF THESE VOICES. MARVI IS SPEAKING AS THE DEFAULT — PICK ONE TO REPLACE IT.`}
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

  // `current` is the readout string -- "OpenRouter / vendor/model" -- not a
  // model id, so it can never match an option. The selection comes from what
  // each provider reports as its configured model instead, which is the same
  // value the Models page writes.
  const configured = rows.find((row) => row.selected)
  const active =
    chosen && chosen.includes('::')
      ? chosen
      : configured
        ? `${configured.provider}::${configured.selected}`
        : ''

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

/**
 * Words appearing as they arrive.
 *
 * The newest few are highlighted briefly, so a transcript that is still being
 * recognised reads as in-progress rather than as a finished sentence. Driven
 * by the text actually growing -- not a timer replaying a complete string,
 * which looks like streaming and tells you nothing.
 */
/**
 * What is being said, under the orb, like subtitles.
 *
 * Fed from the room's own transcription stream rather than the runtime poll:
 * words arrive several times a second and the poll is two seconds wide, so the
 * polled version showed a sentence landing whole, late, having missed the thing
 * that makes live text worth watching.
 *
 * Two lines at most, and the newest one leads. Anything longer stops being a
 * glance and becomes a transcript, which is what Chat is for.
 */
function Subtitles(): React.JSX.Element | null {
  const heard = useStore($heard)
  const spoken = useStore($spoken)

  if (!heard && !spoken) return null

  return (
    <div aria-live="polite" className="voice-subtitles">
      {heard ? (
        <p className={`voice-line is-you${heard.final ? '' : ' is-live'}`} key={heard.id}>
          <span className="voice-who">YOU</span>
          <span className="voice-words">
            <StreamingWords text={subtitleTail(heard.text)} live={!heard.final} />
          </span>
        </p>
      ) : null}
      {spoken ? (
        <p className={`voice-line is-marvi${spoken.final ? '' : ' is-live'}`} key={spoken.id}>
          <span className="voice-who">MARVI</span>
          <span className="voice-words">
            <StreamingWords text={subtitleTail(spoken.text)} live={!spoken.final} />
          </span>
        </p>
      ) : null}
    </div>
  )
}

/**
 * A question Marvi asked, answered here rather than out loud.
 *
 * This is the point of the card, not a convenience on top of it. A spoken
 * answer goes through the recogniser, and the recogniser is where the meaning
 * is lost — "the second one" arrives as "the seconde one", a filename comes
 * back misspelled, a number comes back as a word. Asking a clarifying question
 * and then mis-hearing the answer is worse than not asking, because both sides
 * now believe the ambiguity is settled.
 *
 * Pressing or typing sends exactly those characters into the conversation as
 * the user's own turn. Nothing is waiting on it, so there is no decline button
 * and no token: a question can be answered by saying something else entirely,
 * and that is a complete answer.
 */
function AskedQuestion(): React.JSX.Element | null {
  const runtime = useStore($runtimeState)
  const question = runtime.assistant.question

  // Keyed by the question, so a new one arrives with an empty box rather than
  // with whatever was half-typed in answer to the last. React's own answer to
  // "reset state when the input changes", and it needs no effect.
  return question ? <QuestionCard key={question.id} question={question} /> : null
}

function QuestionCard({ question }: { question: PendingQuestion }): React.JSX.Element {
  const link = useStore($voiceLink)
  const [sending, setSending] = useState(false)
  const [typed, setTyped] = useState('')

  const answer = (text: string): void => {
    const words = text.trim()
    if (!words || sending) return
    setSending(true)
    void (async () => {
      // Into the room first: that is the answer. Clearing the card is
      // bookkeeping, and doing it first would take the question off screen
      // even when there is no call to send it into.
      const said = await sayAsUser(words)
      if (said) await window.marvi?.answerQuestion(question.id, words)
      setSending(false)
    })()
  }

  const live = link === 'live'

  return (
    <div className="voice-question" role="group" aria-label="Marvi asked">
      <p className="voice-question-text">{question.text}</p>
      {question.choices.length ? (
        <div className="voice-question-choices">
          {question.choices.map((choice) => (
            <button
              className="ghost-button"
              disabled={!live || sending}
              key={choice}
              onClick={() => answer(choice)}
              type="button"
            >
              {choice}
            </button>
          ))}
        </div>
      ) : null}
      {/* Always offered, never listed as a choice. "Other" as a fifth button
          costs a click to reach a box that could just be here. */}
      <form
        className="voice-question-other"
        onSubmit={(event) => {
          event.preventDefault()
          answer(typed)
        }}
      >
        <input
          aria-label="Type your answer"
          disabled={!live || sending}
          onChange={(event) => setTyped(event.target.value)}
          placeholder={question.choices.length ? 'Or type an answer…' : 'Type your answer…'}
          value={typed}
        />
        <button className="ghost-button" disabled={!live || sending || !typed.trim()} type="submit">
          Send
        </button>
      </form>
      <p className="voice-question-note">
        {live
          ? 'Answers typed here reach Marvi exactly as written.'
          : 'Join to answer — typing avoids the recogniser mishearing it.'}
      </p>
    </div>
  )
}

/**
 * A credential Marvi asked for, typed here and nowhere else.
 *
 * The value goes renderer → main → Gateway → settings store, and stops. It is
 * never sent into the room the way a `clarify` answer is, never returned to
 * the model, and never logged. Marvi learns the name and that it was saved.
 *
 * That is not caution for its own sake: a key spoken aloud goes through a
 * speech recogniser, into a transcript, and into a model provider's logs. This
 * is the difference between a key on your machine and a key in somebody else's.
 */
function SecretField(): React.JSX.Element | null {
  const runtime = useStore($runtimeState)
  const request = runtime.assistant.secret

  // Keyed, so a second request never inherits the first one's typed value or
  // its revealed state. Remounting is the cheap correct reset here, and for a
  // field holding a credential it is the one that leaves nothing behind.
  return request ? <SecretCard key={request.id} request={request} /> : null
}

function SecretCard({ request }: { request: PendingSecret }): React.JSX.Element {
  const [value, setValue] = useState('')
  const [shown, setShown] = useState(false)
  const [saving, setSaving] = useState(false)

  const settle = (secret: string): void => {
    if (saving) return
    setSaving(true)
    void (async () => {
      await window.marvi?.saveSecret({ id: request.id, name: request.name, value: secret })
      // Cleared here as well as on the next render: the state that held it is
      // this component's, and leaving it set keeps the value in the window.
      setValue('')
      setSaving(false)
    })()
  }

  return (
    <div className="voice-secret" role="group" aria-label={`Marvi asked for ${request.name}`}>
      <p className="voice-secret-why">
        {request.why || `Marvi needs ${request.name} to continue.`}
      </p>
      <form
        className="voice-secret-row"
        onSubmit={(event) => {
          event.preventDefault()
          settle(value)
        }}
      >
        <label htmlFor="marvi-secret">{request.name}</label>
        <input
          autoComplete="off"
          disabled={saving}
          id="marvi-secret"
          onChange={(event) => setValue(event.target.value)}
          spellCheck={false}
          // Masked by default. Shown only while the button is held on, because
          // the reason to reveal it is to check a paste, not to read it out.
          type={shown ? 'text' : 'password'}
          value={value}
        />
        <button
          aria-label={shown ? 'Hide' : 'Show'}
          aria-pressed={shown}
          className="ghost-button"
          onClick={() => setShown((was) => !was)}
          type="button"
        >
          {shown ? 'Hide' : 'Show'}
        </button>
        <button className="ghost-button" disabled={saving || !value} type="submit">
          Save
        </button>
        <button className="ghost-button" disabled={saving} onClick={() => settle('')} type="button">
          Not now
        </button>
      </form>
      <p className="voice-question-note">
        Saved as a setting on this machine. Marvi is told the name, never the value.
      </p>
    </div>
  )
}

function StreamingWords({ text, live }: { text: string; live: boolean }): React.JSX.Element {
  const words = text.split(/\s+/).filter(Boolean)

  return (
    <>
      {words.map((word, index) => (
        <span
          // Keyed by position and word together, so a word that is revised
          // animates in again and one that is merely re-rendered does not.
          className={live && index >= words.length - 2 ? 'voice-word is-fresh' : 'voice-word'}
          key={`${index}-${word}`}
        >
          {word}{' '}
        </span>
      ))}
      {live ? <span aria-hidden="true" className="voice-caret" /> : null}
    </>
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
  const [mode, setMode] = useState<'action' | 'agent'>('action')
  const [prompt, setPrompt] = useState('')
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [effort, setEffort] = useState('')
  const [toolNames, setToolNames] = useState<string[]>([])
  const [delivery, setDelivery] = useState('local')
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
    const next = await window.marvi?.addSchedule({
      name,
      when,
      message,
      insist,
      mode,
      prompt,
      provider,
      model,
      effort,
      tool_names: toolNames,
      delivery
    })
    if (!next) {
      setError('Marvi would not accept that. Check the time.')
      return
    }
    setPage(next)
    setName('')
    setWhen('')
    setMessage('')
    setInsist(false)
    setPrompt('')
    setProvider('')
    setModel('')
    setEffort('')
    setToolNames([])
  }

  const act = async (
    id: number,
    action: 'remove' | 'enable' | 'disable' | 'run'
  ): Promise<void> => {
    const next = await window.marvi?.scheduleAction(id, action)
    if (next) setPage(next)
  }

  return (
    <ControlPage description="Tasks that run at a specific time." title="Schedules">
      {error ? <p className="notice notice-warn">{error}</p> : null}

      <ControlSection icon={Clock3} title="New schedule">
        <div className="schedule-form">
          <label>
            <span>Name</span>
            <input
              value={name}
              placeholder="wake up"
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            <span>When</span>
            <input
              value={when}
              placeholder="07:30, 60 (minutes), or a cron expression"
              onChange={(event) => setWhen(event.target.value)}
            />
          </label>
          <label>
            <span>Message</span>
            <input
              value={message}
              placeholder="Time to get up"
              onChange={(event) => setMessage(event.target.value)}
            />
          </label>
          <label>
            <span>Job type</span>
            <select
              value={mode}
              onChange={(event) => setMode(event.target.value as 'action' | 'agent')}
            >
              <option value="action">Reminder / ARC action</option>
              <option value="agent">Agent task with tools</option>
            </select>
          </label>
          {mode === 'agent' ? (
            <>
              <label className="schedule-wide">
                <span>Task</span>
                <textarea
                  value={prompt}
                  placeholder="A self-contained instruction to run on this schedule"
                  rows={4}
                  onChange={(event) => setPrompt(event.target.value)}
                />
              </label>
              <label>
                <span>Provider</span>
                <input
                  value={provider}
                  placeholder="Auto"
                  onChange={(event) => setProvider(event.target.value)}
                />
              </label>
              <label>
                <span>Model</span>
                <input
                  value={model}
                  placeholder="Auto auxiliary model"
                  onChange={(event) => setModel(event.target.value)}
                />
              </label>
              <label>
                <span>Reasoning</span>
                <select value={effort} onChange={(event) => setEffort(event.target.value)}>
                  {(page?.efforts ?? ['', 'low', 'medium', 'high']).map((item) => (
                    <option key={item || 'auto'} value={item}>
                      {item || 'Auto'}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Delivery</span>
                <select value={delivery} onChange={(event) => setDelivery(event.target.value)}>
                  {(
                    page?.delivery_targets ?? [
                      { id: 'local', name: 'Local (save only)', available: true }
                    ]
                  ).map((target) => (
                    <option key={target.id} value={target.id} disabled={!target.available}>
                      {target.name}
                    </option>
                  ))}
                </select>
              </label>
              <fieldset className="schedule-tools schedule-wide">
                <legend>Tools</legend>
                <small>No selection gives the job the current full catalogue.</small>
                <div>
                  {(page?.tools ?? []).map((tool) => (
                    <label key={tool}>
                      <input
                        type="checkbox"
                        checked={toolNames.includes(tool)}
                        onChange={(event) =>
                          setToolNames((current) =>
                            event.target.checked
                              ? [...current, tool]
                              : current.filter((item) => item !== tool)
                          )
                        }
                      />
                      <span>{tool}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
            </>
          ) : null}
          <label className="schedule-insist">
            <input
              type="checkbox"
              checked={insist}
              onChange={(event) => setInsist(event.target.checked)}
            />
            <span>
              Speak anyway
              {/* The opt-in. Off by default because an hourly check firing out
                loud at 3am is what quiet hours exists to prevent. */}
              <small>Ignore quiet hours and sleep mode. For an alarm you mean.</small>
            </span>
          </label>
          <button
            className="phase"
            type="button"
            disabled={!name || !when || (mode === 'agent' && !prompt.trim())}
            onClick={() => void add()}
          >
            Add schedule
          </button>
        </div>
      </ControlSection>

      <ControlSection icon={CalendarDays} title="Schedules">
        {!page ? (
          <ProcessingCard
            compact
            detail="Reading the local schedule registry."
            title="Loading schedules"
          />
        ) : null}
        <div className="service-list">
          {(page?.schedules ?? []).map((row) => (
            <div className="service-row" key={row.id}>
              <span className="service-name">{row.name}</span>
              <span
                className={`service-state state-${
                  row.last_error ? 'error' : row.enabled ? 'ready' : 'pending'
                }`}
              >
                {row.last_error ? 'Failed' : row.enabled ? 'On' : 'Off'}
                {row.insist ? ' · insists' : ''}
              </span>
              <small>
                {row.kind === 'interval' ? `every ${row.expression} minutes` : row.expression} /{' '}
                {row.mode === 'agent' ? 'agent task' : row.action}
              </small>
              {row.mode === 'agent' ? (
                <small>
                  {row.provider || 'auto provider'} / {row.model || 'auto model'} /{' '}
                  {row.effort || 'auto reasoning'}
                  {' · '}
                  {row.tool_names.length ? `${row.tool_names.length} tools` : 'all tools'}
                  {' · '}
                  {row.delivery}
                </small>
              ) : null}
              {row.prompt ? <small>{row.prompt}</small> : null}
              {row.message ? <small>{row.message}</small> : null}
              {row.last_error ? (
                <small className="provider-cooldown">{row.last_error}</small>
              ) : row.last_run ? (
                <small>last run {row.last_run}</small>
              ) : null}
              {row.last_output ? (
                <small className="schedule-output">{row.last_output}</small>
              ) : null}
              <div className="provider-actions">
                <button className="phase" type="button" onClick={() => void act(row.id, 'run')}>
                  Run now
                </button>
                <button
                  className="phase"
                  type="button"
                  onClick={() => void act(row.id, row.enabled ? 'disable' : 'enable')}
                >
                  {row.enabled ? 'Pause' : 'Resume'}
                </button>
                <button
                  className="phase danger"
                  type="button"
                  onClick={() => void act(row.id, 'remove')}
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>

        {page && page.schedules.length === 0 ? (
          <ControlEmpty
            description="Create one above when you want a task to run later."
            title="Nothing scheduled"
          />
        ) : null}
      </ControlSection>
    </ControlPage>
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
    <ControlPage description="Long-running local services that extend Marvi." title="Plugins">
      {error ? <p className="notice notice-warn">{error}</p> : null}

      {!page ? (
        <ProcessingCard
          compact
          detail="Reading declared plugins and their local state."
          title="Loading plugins"
        />
      ) : null}

      <ControlSection icon={Box} title="Installed and available">
        <div className="service-list">
          {(page?.plugins ?? []).map((plugin) => (
            <div className="service-row" key={plugin.name}>
              <span className="service-name">{plugin.title}</span>
              <span
                className={`service-state state-${
                  !plugin.supported || (plugin.installed && !plugin.running)
                    ? 'error'
                    : plugin.installed
                      ? 'ready'
                      : busy === plugin.name
                        ? 'starting'
                        : 'pending'
                }`}
              >
                {busy === plugin.name
                  ? 'Working'
                  : plugin.installed
                    ? plugin.running
                      ? `Installed ${plugin.version ? `v${plugin.version}` : ''}`.trim()
                      : 'Not running'
                    : plugin.detail}
              </span>
              {plugin.why ? <small>{plugin.why}</small> : null}
              <small className="plugin-repo">
                {plugin.repo}
                {plugin.ref ? ` (${plugin.ref})` : ' (default branch)'}
                {plugin.commit ? ` @${plugin.commit}` : ''}
              </small>
              {plugin.installed && (!plugin.supported || !plugin.running) ? (
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
                      Install
                    </button>
                    <button className="phase" type="button" onClick={() => setConfirming('')}>
                      Cancel
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
                        Update
                      </button>
                      <button
                        className="phase danger"
                        type="button"
                        disabled={!!busy}
                        onClick={() => void act(plugin.name, 'remove')}
                      >
                        Remove
                      </button>
                    </>
                  ) : (
                    <button
                      className="phase"
                      type="button"
                      disabled={!!busy}
                      onClick={() => setConfirming(plugin.name)}
                    >
                      Install
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>

        {(page?.plugins ?? []).length === 0 ? (
          <ControlEmpty
            description="Add a declaration to config/plugin-sources.json."
            title="No plugins declared"
          />
        ) : null}
      </ControlSection>
      <ControlSection icon={Wrench} title="Plugin storage">
        <button className="phase" type="button" onClick={() => void load()}>
          Check again
        </button>
        {page ? (
          <>
            <small>Checkouts · {page.install_root}</small>
            {/* Named because removing a plugin keeps its data, and someone
              looking for their room history should not have to guess. */}
            <small>Plugin data · {page.data_root}</small>
          </>
        ) : null}
      </ControlSection>
    </ControlPage>
  )
}

function SkillsPanel(): React.JSX.Element {
  const [store, setStore] = useState<StoreSkill[]>([])
  const [sources, setSources] = useState<string[]>([])
  const [filter, setFilter] = useState('')
  const [review, setReview] = useState<SkillReview | null>(null)
  const [proposal, setProposal] = useState<SkillProposal | null>(null)
  const [installed, setInstalled] = useState<SkillsPage | null>(null)
  const [busy, setBusy] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [storeFailed, setStoreFailed] = useState(false)

  const load = useCallback(async (): Promise<void> => {
    const page = await window.marvi?.getSkillStore()
    // `loaded` regardless. A store fetch that failed and one that has not
    // arrived yet look identical to the code that draws the spinner, and the
    // page spun forever: nine repositories and 488 frontmatter requests took
    // 114 seconds against an IPC call that gives up at sixty, so it could
    // never succeed and never stopped saying "Loading".
    setStore(page?.skills ?? [])
    setSources(page?.sources ?? [])
    setStoreFailed(!page)
    setLoaded(true)
    setInstalled((await window.marvi?.getInstalledSkills()) ?? null)
  }, [])

  useEffect(() => {
    let disposed = false
    // Two loads, not one. What is installed is on this disk and answers
    // immediately; the store reaches nine GitHub repositories. Waiting for the
    // second before showing the first meant the page showed nothing at all for
    // as long as the network took.
    void (async () => {
      const mine = await window.marvi?.getInstalledSkills()
      if (!disposed) setInstalled(mine ?? null)
    })()
    void (async () => {
      const page = await window.marvi?.getSkillStore()
      if (disposed) return
      setStore(page?.skills ?? [])
      setSources(page?.sources ?? [])
      setStoreFailed(!page)
      setLoaded(true)
    })()
    return () => {
      disposed = true
    }
  }, [])

  // A proposal arrives from a conversation happening somewhere else, so this
  // page has to keep asking rather than read once when it opened.
  useEffect(() => {
    let disposed = false
    const look = async (): Promise<void> => {
      const found = await window.marvi?.getSkillProposal()
      if (!disposed) setProposal(found ?? null)
    }
    void look()
    const timer = setInterval(() => void look(), 10_000)
    return () => {
      disposed = true
      clearInterval(timer)
    }
  }, [])

  const settle = async (accept: boolean): Promise<void> => {
    setBusy('proposal')
    try {
      await window.marvi?.settleSkillProposal(accept)
      setProposal(null)
      if (accept) await load()
    } finally {
      setBusy('')
    }
  }

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
    <ControlPage
      description="Instructions that teach Marvi how to complete specific work."
      title="Skills"
    >
      {proposal ? (
        <ControlSection icon={Wrench} title="Learned from a conversation">
          <div className="skill-review">
            <div className="panel-label">{proposal.name}</div>
            <p>{proposal.description || proposal.why}</p>
            <small className="provider-cooldown">
              {proposal.act === 'patch'
                ? 'This replaces the skill of that name, in full.'
                : 'A new skill. Nothing is written until you accept it.'}
            </small>
            {proposal.why ? <small>Because · {proposal.why}</small> : null}
            <pre className="service-output skill-body">{proposal.body}</pre>
            <div className="provider-actions">
              <button
                className="phase active"
                type="button"
                disabled={busy === 'proposal'}
                onClick={() => void settle(true)}
              >
                {proposal.act === 'patch' ? 'Replace' : 'Add skill'}
              </button>
              <button
                className="phase"
                type="button"
                disabled={busy === 'proposal'}
                onClick={() => void settle(false)}
              >
                Discard
              </button>
            </div>
          </div>
        </ControlSection>
      ) : null}
      {installed && installed.skills.length > 0 ? (
        <ControlSection icon={Wrench} title="Your skills">
          <div className="service-list">
            {installed.skills.map((skill) => (
              <div className="service-row" key={skill.name}>
                <span className="service-name">{skill.name}</span>
                <span
                  className={`service-state state-${
                    !skill.applies
                      ? 'pending'
                      : skill.usage.state === 'active'
                        ? 'ready'
                        : 'pending'
                  }`}
                >
                  {!skill.applies
                    ? 'Not here'
                    : skill.usage.pinned
                      ? 'Pinned'
                      : skill.usage.state === 'active'
                        ? ''
                        : skill.usage.state}
                </span>
                <small>{skill.description}</small>
                <small>
                  {/* The number nothing used to know. Everything else on this
                      row is a decision that needs it. */}
                  {skill.usage.uses === 0
                    ? 'Never used'
                    : `Used ${skill.usage.uses} time${skill.usage.uses === 1 ? '' : 's'}${
                        skill.usage.lastUsed
                          ? `, last on ${skill.usage.lastUsed.slice(0, 10)}`
                          : ''
                      }`}
                  {skill.usage.mine ? ' · written by Marvi' : ''}
                  {!skill.applies && skill.platforms.length > 0
                    ? ` · for ${skill.platforms.join(', ')}`
                    : ''}
                  {!skill.applies && skill.requires.length > 0
                    ? ` · needs ${skill.requires.join(', ')}`
                    : ''}
                </small>
                {/* Only Marvi's own can be swept, so only they need pinning.
                    A skill you wrote is yours and is never touched. */}
                {skill.usage.mine ? (
                  <div className="provider-actions">
                    <button
                      className="phase"
                      type="button"
                      disabled={!!busy}
                      onClick={() => {
                        setBusy(skill.name)
                        void window.marvi
                          ?.pinSkill(skill.name, !skill.usage.pinned)
                          .then(() => load())
                          .finally(() => setBusy(''))
                      }}
                    >
                      {skill.usage.pinned ? 'Unpin' : 'Keep always'}
                    </button>
                    <button
                      className="phase"
                      type="button"
                      disabled={!!busy}
                      onClick={() => {
                        setBusy(skill.name)
                        void window.marvi
                          ?.archiveSkill(skill.name)
                          .then(() => load())
                          .finally(() => setBusy(''))
                      }}
                    >
                      Archive
                    </button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
          {installed.archived.length > 0 ? (
            <ControlRow
              action={
                <div className="provider-actions">
                  {installed.archived.slice(0, 4).map((name) => (
                    <button
                      className="phase"
                      key={name}
                      type="button"
                      disabled={!!busy}
                      onClick={() => {
                        setBusy(name)
                        void window.marvi
                          ?.restoreSkill(name)
                          .then(() => load())
                          .finally(() => setBusy(''))
                      }}
                    >
                      {name}
                    </button>
                  ))}
                </div>
              }
              description="Set aside because nothing had used them in a long time. Nothing was deleted; press one to bring it back."
              icon={Database}
              title="Archived"
            />
          ) : null}
        </ControlSection>
      ) : null}
      <ControlSection icon={Database} title="Catalog">
        <div className="context-line">
          <span>Sources</span>
          <strong>{sources.join(', ') || 'None configured'}</strong>
        </div>

        <input
          className="skill-search"
          type="text"
          placeholder="Search skills"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />

        {/* The review sheet: instructions in full, warnings, then the button. */}
        {review ? (
          <div className="skill-review">
            <div className="panel-label">{review.skill.name}</div>
            <p>{review.skill.description}</p>
            {review.warnings.map((warning) => (
              <small className="provider-cooldown" key={warning}>
                {warning}
              </small>
            ))}
            {review.tools?.still_sensitive?.length ? (
              <small className="provider-cooldown">
                It names sensitive tools ({review.tools.still_sensitive.join(', ')}). Those still
                ask you every time.
              </small>
            ) : null}
            {/* Read before Marvi reads it. The body used to be shown with an
                Install button under it, and "you were shown it" is not a
                control — nobody reads five hundred lines before clicking. */}
            {review.scan && review.scan.findings.length > 0 ? (
              <div className="skill-scan">
                <div className="panel-label">
                  {review.scan.blocked ? 'Not recommended' : 'Worth knowing'} — {review.scan.reason}
                </div>
                {review.scan.findings.map((finding) => (
                  <small
                    className={finding.severity === 'danger' ? 'provider-cooldown' : ''}
                    key={finding.rule}
                  >
                    <strong>{finding.rule.replace(/-/g, ' ')}</strong> · {finding.why}
                    <br />
                    <code>{finding.quote}</code>
                  </small>
                ))}
              </div>
            ) : null}
            <pre className="service-output skill-body">{review.instructions}</pre>
            <div className="provider-actions">
              <button
                className={review.scan?.blocked ? 'phase danger' : 'phase active'}
                type="button"
                disabled={busy === 'installing'}
                onClick={() => void confirm()}
              >
                {busy === 'installing'
                  ? 'Installing'
                  : review.scan?.blocked
                    ? 'Install anyway'
                    : 'Install'}
              </button>
              <button className="phase" type="button" onClick={() => setReview(null)}>
                Cancel
              </button>
            </div>
          </div>
        ) : null}

        {!loaded ? (
          <ProcessingCard
            compact
            detail="Reading the configured sources. The first time takes a few seconds; after that it is cached."
            title="Loading skill store"
          />
        ) : storeFailed ? (
          <ControlRow
            action={
              <ControlButton
                onClick={() => {
                  setLoaded(false)
                  void load()
                }}
              >
                Try again
              </ControlButton>
            }
            description="The configured sources could not be reached. Everything already installed is above and still works."
            icon={ShieldAlert}
            title="Could not reach the skill store"
          />
        ) : store.length === 0 ? (
          <ControlEmpty
            description="Add a skill source to populate this catalog."
            title="No skills available"
          />
        ) : (
          <div className="service-list">
            {shown.map((skill) => (
              <div className="service-row" key={`${skill.repo}/${skill.name}`}>
                <span className="service-name">{skill.name}</span>
                <span className={`service-state state-${skill.installed ? 'ready' : 'pending'}`}>
                  {skill.installed ? 'Installed' : ''}
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
                      Remove
                    </button>
                  ) : (
                    <button
                      className="phase"
                      type="button"
                      disabled={!!busy}
                      onClick={() => void open(skill)}
                    >
                      {busy === skill.name ? 'Fetching' : 'Review and install'}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </ControlSection>
    </ControlPage>
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
    <ControlPage
      description="Local history of tool requests, approvals, and results."
      title="Activity"
    >
      <ControlSection icon={History} title="Tool activity">
        {events.length === 0 ? (
          <ControlEmpty
            description="Tool requests and their outcomes will appear here. Nothing is uploaded."
            icon={Clock3}
            title="No activity yet"
          />
        ) : (
          events.map((event, index) => (
            <ControlRow
              action={
                <ControlPill tone={event.event === 'failed' ? 'danger' : 'neutral'}>
                  {event.event}
                </ControlPill>
              }
              description={`${event.at.slice(11, 19)} · ${event.mode}${Object.keys(event.arguments).length > 0 ? ` · ${JSON.stringify(event.arguments)}` : ''}${event.detail ? ` · ${event.detail}` : ''}`}
              key={`${event.at}-${index}`}
              title={event.tool.replaceAll('_', ' ')}
            />
          ))
        )}
      </ControlSection>
    </ControlPage>
  )
}

function PagePanel({ page }: { page: Page }): React.JSX.Element {
  // The fallback for a sidebar page with no purpose-built surface yet.
  const descriptions: Record<Page, string> = {
    Overview: '',
    Voice: '',
    Chat: '',
    Room: '',
    Activity: 'Local event and tool history.',
    Identity: "Marvi's identity and your standing preferences.",
    Graph: 'What Marvi knows, and how it connects.',
    Mind: 'Autonomous decisions and initiative controls.',
    Vision: 'Local presence and gesture processing from the room camera.'
  }

  return (
    <ControlPage description={descriptions[page]} title={page}>
      <ControlEmpty
        description="This module has no controls to show yet."
        icon={Sparkles}
        title="Nothing here yet"
      />
    </ControlPage>
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
    <ControlPage
      description="Repair the local runtime or install missing components from a terminal."
      title="Maintenance"
    >
      <ControlSection icon={Wrench} title="Diagnostics and repair">
        <CommandCard command="marvi doctor" title="Find problems">
          <p>Check the local stack and name each available fix.</p>
        </CommandCard>
        <CommandCard command="marvi setup" title="Install missing components">
          <p>Install missing models, browsers, and dependencies.</p>
        </CommandCard>
        <CommandCard command="marvi models list" title="Review installed models">
          <p>Show installed components and their verification state.</p>
        </CommandCard>
        <CommandCard command="marvi diagnostics" title="Prepare a bug report">
          <p>Copy a redacted diagnostics summary.</p>
        </CommandCard>
      </ControlSection>
      <ControlRow
        description="Open a new terminal or rerun the installer if the command is not available."
        icon={SquareTerminal}
        title="Command not found?"
      />
    </ControlPage>
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
  const voiceOpen = (SETTINGS_VOICE_PAGES as readonly string[]).includes(page)

  useEffect(() => {
    const escape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', escape)
    return () => window.removeEventListener('keydown', escape)
  }, [onClose])

  return (
    <div
      className="settings-shell"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      role="presentation"
    >
      <div aria-label="Settings" aria-modal="true" className="settings-frame" role="dialog">
        <UiTooltip label="Close settings" side="left">
          <button
            aria-label="Close settings"
            className="settings-close"
            onClick={onClose}
            type="button"
          >
            <AbstractIcon name="close" size={14} />
          </button>
        </UiTooltip>
        <nav className="settings-rail" aria-label="Settings sections">
          {SETTINGS_GROUPS.map((group, index) => (
            <div
              className={group.gapBefore ? 'settings-group has-gap' : 'settings-group'}
              key={index}
            >
              {group.items.map((item) =>
                item === 'Voice' ? (
                  <div className="settings-nav-family" key={item}>
                    <button
                      aria-expanded={voiceOpen}
                      className={voiceOpen ? 'settings-link active' : 'settings-link'}
                      onClick={() => onNavigate(voiceOpen ? page : 'Speech recognition')}
                      type="button"
                    >
                      <AbstractIcon name={SETTINGS_ICONS[item]} size={16} />
                      <span>Voice</span>
                      <span aria-hidden="true" className="settings-nav-chevron">
                        {voiceOpen ? '−' : '+'}
                      </span>
                    </button>
                    {voiceOpen ? (
                      <div className="settings-subnav">
                        {SETTINGS_VOICE_PAGES.map((voicePage) => (
                          <button
                            aria-current={page === voicePage ? 'page' : undefined}
                            className={
                              page === voicePage
                                ? 'settings-link settings-sublink active'
                                : 'settings-link settings-sublink'
                            }
                            key={voicePage}
                            onClick={() => onNavigate(voicePage)}
                            type="button"
                          >
                            <AbstractIcon name={SETTINGS_ICONS[voicePage]} size={16} />
                            <span>{voicePage}</span>
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <button
                    aria-current={page === item ? 'page' : undefined}
                    className={page === item ? 'settings-link active' : 'settings-link'}
                    key={item}
                    onClick={() => onNavigate(item)}
                    type="button"
                  >
                    <AbstractIcon name={SETTINGS_ICONS[item]} size={16} />
                    <span>{item}</span>
                  </button>
                )
              )}
            </div>
          ))}
        </nav>

        <div className="settings-content">
          <div className="settings-scroll">
            {page === 'Providers' ? (
              <ProvidersPanel />
            ) : page === 'Models' ? (
              <ModelsPanel />
            ) : page === 'Usage' ? (
              <UsagePanel />
            ) : page === 'Accounts' ? (
              <AccountsPanel />
            ) : page === 'Skills' ? (
              <SkillsPanel />
            ) : page === 'Plugins' ? (
              <PluginsPanel />
            ) : page === 'Speech recognition' ? (
              <SpeechRecognitionPanel />
            ) : page === 'Voice synthesis' ? (
              <VoiceSynthesisPanel />
            ) : page === 'Wake word' ? (
              <WakeWordPanel />
            ) : page === 'Memory' ? (
              <MemorySettingsPanel />
            ) : page === 'Workspace' ? (
              <WorkspacePanel />
            ) : page === 'Appearance' ? (
              <AppearancePanel />
            ) : page === 'Preferences' ? (
              <PreferencesPanel runtime={runtime} />
            ) : page === 'Schedules' ? (
              <SchedulesPanel />
            ) : page === 'Maintenance' ? (
              <MaintenancePanel />
            ) : (
              <AboutPanel fallbackVersion={version} runtime={runtime} />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function SpeechRecognitionPanel(): React.JSX.Element {
  return (
    <ControlPage
      className="settings-page"
      description="Configure speech-to-text accuracy and where local recognition runs."
      title="Speech recognition"
    >
      <ControlSection icon={Languages} title="Language">
        <UnderstandRow />
      </ControlSection>
      <ControlSection icon={Mic} title="Speech to text · STT">
        <div>
          <p>
            How far ahead the recogniser listens before committing a word. Longer is more accurate
            and lags further behind you; it does not delay the answer, because the last of what you
            said is flushed the moment you stop.
          </p>
        </div>
        <RecognitionSettings />
      </ControlSection>
    </ControlPage>
  )
}

function VoiceSynthesisPanel(): React.JSX.Element {
  return (
    <ControlPage
      className="settings-page"
      description="Choose the voice Marvi uses when turning responses into speech."
      title="Voice synthesis"
    >
      <ControlSection icon={Languages} title="Language">
        <SpeakRow />
      </ControlSection>
      <ControlSection icon={Waves} title="Text to speech · TTS">
        <div>
          <p>The voice Marvi speaks in. This choice is also available beside the Voice orb.</p>
        </div>
        <VoicePicker />
      </ControlSection>
    </ControlPage>
  )
}

function WakeWordPanel(): React.JSX.Element {
  return (
    <ControlPage
      className="settings-page"
      description="Set the local phrase that starts a hands-free voice session."
      title="Wake word"
    >
      <ControlSection icon={Radio} title="Wake word">
        <div>
          <p>
            A small process that starts at login and waits for her name. Saying &ldquo;Marvi&rdquo;
            joins hands-free, exactly as pressing Join does, and opens Marvi first if she is closed.
          </p>
        </div>
        <WakeSettings />
      </ControlSection>
    </ControlPage>
  )
}

/** The two things about the recogniser worth changing. */
function RecognitionSettings(): React.JSX.Element {
  const [lookahead, setLookahead] = useState('')
  const [device, setDevice] = useState('')

  useEffect(() => {
    let gone = false
    void (async () => {
      const page = await window.marvi?.getProviders()
      if (gone || !page) return
      const values = (page as unknown as { settings?: Record<string, string> }).settings ?? {}
      setLookahead(values['MARVI_STT_LOOKAHEAD'] ?? '2.0')
      setDevice(values['MARVI_STT_DEVICE'] ?? 'cpu')
    })()
    return () => {
      gone = true
    }
  }, [])

  const save = (values: Record<string, string>): void => {
    void window.marvi?.setProviderSettings(values)
  }

  return (
    <>
      <ControlRow
        action={
          <Picker
            options={[
              { value: '0.8', label: 'Fast', detail: 'Subtitles keep up; more mistakes' },
              { value: '2.0', label: 'Accurate', detail: 'The default. Two seconds behind you' },
              { value: '3.0', label: 'Most accurate', detail: 'Slowest subtitles' }
            ]}
            value={lookahead}
            onChange={(next) => {
              setLookahead(next)
              save({ MARVI_STT_LOOKAHEAD: next })
            }}
            placeholder="Accurate"
          />
        }
        description="Longer lookahead improves accuracy while subtitles follow farther behind."
        title="Recognition accuracy"
      />
      <ControlRow
        action={
          <Picker
            options={[
              { value: 'cpu', label: 'Processor', detail: 'Leaves the graphics card to the voice' },
              { value: 'cuda', label: 'Graphics card', detail: 'Faster, shares the card' }
            ]}
            value={device}
            onChange={(next) => {
              setDevice(next)
              save({ MARVI_STT_DEVICE: next })
            }}
            placeholder="Processor"
          />
        }
        description="Marvi restarts the voice worker after this changes."
        title="Inference device"
      />
    </>
  )
}

/**
 * Where Marvi may read, where she may write, and what is off limits to both.
 *
 * Three settings rather than one, because the honest answer is usually
 * asymmetric: read the whole disk, write only where I said. The blacklist
 * holds over both — including the general setting, which is the only reason
 * the general setting is on offer.
 *
 * The built-in rules are shown and cannot be removed. A deny list with
 * invisible entries in it is one nobody can reason about, and the first time
 * an invisible entry bites it reads as a bug rather than as a rule.
 */
function WorkspacePanel(): React.JSX.Element {
  const [policy, setPolicy] = useState<WorkspacePolicy | null>(null)
  const [error, setError] = useState('')
  const [adding, setAdding] = useState('')

  useEffect(() => {
    let gone = false
    void (async () => {
      const page = await window.marvi?.getWorkspace()
      if (!gone) setPolicy(page ?? null)
    })()
    return () => {
      gone = true
    }
  }, [])

  const apply = async (update: WorkspaceUpdate): Promise<void> => {
    const next = (await window.marvi?.setWorkspace(update)) as
      (WorkspacePolicy & { error?: string }) | null
    if (!next) return setError('Marvi is not answering.')
    // A refusal says why. Showing nothing would read as the switch not working.
    if (typeof next.error === 'string') return setError(next.error)
    setError('')
    setPolicy(next)
  }

  const scopeOptions = (what: 'Reading' | 'Writing'): PickerOption[] => [
    {
      value: 'strict',
      label: 'Workspace only',
      detail: `${what} anywhere else is refused`
    },
    {
      value: 'general',
      label: 'Anywhere on this PC',
      detail: 'Still refused everything on the blacklist'
    }
  ]

  return (
    <ControlPage
      className="settings-page"
      description="Which folders the file tools may touch, and what is refused to all of them."
      title="Workspace"
    >
      <ControlSection
        description="Where a path without a drive letter means. Marvi works here by default."
        icon={FolderOpen}
        title="Workspace folder"
      >
        <ControlRow
          action={
            <button
              className="ghost-button"
              onClick={() => {
                void (async () => {
                  const chosen = await window.marvi?.chooseFolder()
                  if (chosen) void apply({ root: chosen })
                })()
              }}
              type="button"
            >
              Choose folder
            </button>
          }
          description={
            policy?.root
              ? policy.rootExists
                ? 'Relative paths resolve here, in both modes.'
                : 'This folder is missing. Every file tool refuses until it is set again.'
              : 'Nothing is set, so Marvi has nowhere to work and says so when asked.'
          }
          title={policy?.root || 'No workspace chosen'}
        />
      </ControlSection>

      <ControlSection
        description="Asked separately, because the useful answer is usually different for each."
        icon={Eye}
        title="How far the tools may reach"
      >
        <ControlRow
          action={
            <Picker
              options={scopeOptions('Reading')}
              value={policy?.readScope ?? 'strict'}
              onChange={(next) => void apply({ read_scope: next })}
              placeholder="Workspace only"
            />
          }
          description={`Used by ${(policy?.tools.read ?? []).join(', ') || 'the reading tools'}.`}
          title="Reading"
        />
        <ControlRow
          action={
            <Picker
              options={scopeOptions('Writing')}
              value={policy?.writeScope ?? 'strict'}
              onChange={(next) => void apply({ write_scope: next })}
              placeholder="Workspace only"
            />
          }
          description={`Used by ${(policy?.tools.write ?? []).join(', ') || 'the writing tools'}.`}
          title="Writing"
        />
      </ControlSection>

      <ControlSection
        description="Refused in both modes. A folder covers everything inside it; an entry with a * matches by name anywhere."
        icon={ShieldOff}
        title="Never touch"
      >
        <div className="workspace-blacklist">
          {(policy?.blacklist ?? []).map((entry) => (
            <div className="workspace-entry" key={entry}>
              <code>{entry}</code>
              <button
                aria-label={`Remove ${entry}`}
                className="ghost-button"
                onClick={() =>
                  void apply({
                    blacklist: (policy?.blacklist ?? []).filter((item) => item !== entry)
                  })
                }
                type="button"
              >
                Remove
              </button>
            </div>
          ))}
          {policy && policy.blacklist.length === 0 ? (
            <p className="control-note">Nothing added. The built-in rules below still apply.</p>
          ) : null}
          <form
            className="workspace-add"
            onSubmit={(event) => {
              event.preventDefault()
              const entry = adding.trim()
              if (!entry) return
              setAdding('')
              void apply({ blacklist: [...(policy?.blacklist ?? []), entry] })
            }}
          >
            <input
              aria-label="Path or pattern to refuse"
              onChange={(event) => setAdding(event.target.value)}
              placeholder="C:\\Users\\me\\Private   or   *.key"
              value={adding}
            />
            <button className="ghost-button" type="submit">
              Add
            </button>
          </form>
        </div>
      </ControlSection>

      <ControlSection
        description="Environment files, key stores, and Marvi's own settings. Writing to them is always refused — ask her for a key instead and the value never passes through the model."
        icon={KeyRound}
        title="Files with secrets in them"
      >
        <ControlRow
          action={
            <Picker
              options={[
                {
                  value: 'off',
                  label: 'Refuse',
                  detail: 'She cannot open them at all'
                },
                {
                  value: 'masked',
                  label: 'Names only',
                  detail: 'Which settings exist, never their values'
                },
                {
                  value: 'full',
                  label: 'Values too',
                  detail: 'Keys reach the model that answers you'
                }
              ]}
              value={policy?.secretAccess ?? 'off'}
              onChange={(next) => void apply({ secret_access: next })}
              placeholder="Refuse"
            />
          }
          description={
            '“Is my key set?” and “what is my key?” look like the same question. ' +
            'Names only answers the first without answering the second.'
          }
          title="Reading them"
        />
      </ControlSection>

      <ControlSection
        description="These hold whatever the settings say. Reading a credential is governed by the setting above; the rest cannot be lifted at all."
        icon={ShieldAlert}
        title="Always refused"
      >
        <div className="workspace-builtin">
          {(policy?.builtin ?? []).map((rule) => (
            <div className="workspace-entry" key={rule.pattern}>
              <code>{rule.pattern}</code>
              <span>
                {rule.why}
                {rule.secret ? ' — reading is a setting' : rule.reading ? '' : ' — writing only'}
              </span>
            </div>
          ))}
        </div>
      </ControlSection>

      {error ? <p className="control-note is-danger">{error}</p> : null}
    </ControlPage>
  )
}

/**
 * Which language Marvi listens in, and which she answers in.
 *
 * Shared by the two voice pages because they are two halves of one setting and
 * a copy each is how they drift. The honest part is `enforceable`: only English
 * has a recogniser that cannot produce another language, so every other choice
 * is a preference the multilingual model is free to ignore — and the page says
 * so rather than implying a lock it cannot deliver.
 */
function useLanguage(): {
  policy: LanguagePolicy | null
  apply: (update: LanguageUpdate) => void
} {
  const [policy, setPolicy] = useState<LanguagePolicy | null>(null)

  useEffect(() => {
    let gone = false
    void (async () => {
      const page = await window.marvi?.getLanguage()
      if (!gone) setPolicy(page ?? null)
    })()
    return () => {
      gone = true
    }
  }, [])

  const apply = (update: LanguageUpdate): void => {
    void (async () => {
      const next = await window.marvi?.setLanguage(update)
      if (next) setPolicy(next)
    })()
  }
  return { policy, apply }
}

/** The half of the language setting that belongs to the recogniser. */
function UnderstandRow(): React.JSX.Element {
  const { policy, apply } = useLanguage()
  const understand = policy?.understand ?? 'auto'
  const missing = understand === 'en' && policy !== null && !policy.englishModelInstalled

  return (
    <ControlRow
      action={
        <Picker
          options={(policy?.understandOptions ?? []).map((option) => ({
            value: option.code,
            label: option.name,
            detail: option.locked
              ? option.code === 'auto'
                ? 'Transcribes whatever it hears'
                : 'A different model, which knows no other language'
              : 'A preference — this model decides for itself'
          }))}
          value={understand}
          onChange={(next) => apply({ understand: next })}
          placeholder="Any language"
        />
      }
      description={
        missing
          ? 'The English-only recogniser is not installed, so this is doing nothing yet. Install “Speech recognition (English only)” on the Maintenance page.'
          : understand === 'en'
            ? 'A different model with no other language in its vocabulary. It cannot mishear you into one.'
            : understand === 'auto'
              ? 'She transcribes whatever language she hears, and answers in it unless told otherwise.'
              : 'Parakeet takes no language argument, so this is a preference rather than a lock. Only English has a model that can enforce it.'
      }
      title="Language she listens for"
    />
  )
}

/** The half that belongs to the voice, and to what she writes. */
function SpeakRow(): React.JSX.Element {
  const { policy, apply } = useLanguage()
  const options = policy?.speakOptions ?? []

  return (
    <ControlRow
      action={
        <Picker
          options={options.map((option) => ({ value: option.code, label: option.name }))}
          value={policy?.speak ?? 'en'}
          onChange={(next) => apply({ speak: next })}
          placeholder="English"
        />
      }
      description={
        options.length > 1
          ? 'What she writes and what the voice pronounces. Both, so they cannot disagree.'
          : 'Only languages with an installed voice are offered: one without is read with English phonemes, which is noise rather than an accent.'
      }
      title="Language she answers in"
    />
  )
}

function AppearancePanel(): React.JSX.Element {
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
  const [petPreferences, setPetPreferences] = useState<PetPreferences>({
    ...DEFAULT_PET_PREFERENCES
  })

  useEffect(() => {
    void window.marvi?.getDisplays().then(setDisplays)
    void window.marvi?.getIslandPlacement().then(setPlacement)
    void window.marvi?.getPetPreferences().then(setPetPreferences)
  }, [])

  const updatePlacement = (next: IslandPlacement): void => {
    setPlacement(next)
    void window.marvi?.setIslandPlacement(next).then(setPlacement)
  }

  const updatePet = (next: PetPreferences): void => {
    setPetPreferences(next)
    void window.marvi?.setPetPreferences(next).then(setPetPreferences)
  }

  return (
    <ControlPage
      className="settings-page"
      description="Shape the control center, Dynamic Island, and desktop companion."
      title="Appearance"
    >
      <ControlSection icon={Sparkles} title="Window and backdrop">
        <ControlRow
          action={
            <label className="setting-range">
              <span>{translucency}%</span>
              <input
                aria-label="Window translucency"
                max={100}
                min={0}
                onChange={(event) => setTranslucency(Number(event.target.value))}
                type="range"
                value={translucency}
              />
            </label>
          }
          description="Show the desktop through the control center."
          title="Window translucency"
        />
        <ControlRow
          action={
            <select
              aria-label="Backdrop mode"
              onChange={(event) => setBackgroundMode(event.target.value as typeof backgroundMode)}
              value={backgroundMode}
            >
              <option value="electricGaze">Electric gaze</option>
              <option value="none">Off</option>
            </select>
          }
          description="The animated ASCII backdrop is packaged locally."
          title="Backdrop"
        />
        <ControlRow
          action={
            <label className="setting-range">
              <span>{backgroundOpacity}%</span>
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
          }
          description="Adjust how strongly the backdrop appears behind page content."
          title="Backdrop opacity"
        />
      </ControlSection>

      <ControlSection icon={Info} title="Dynamic Island placement">
        <ControlRow
          action={
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
              <option value="auto">Auto · current</option>
              {displays.map((display) => (
                <option key={display.id} value={display.id}>
                  {display.label}
                  {display.primary ? ' · primary' : ''}
                </option>
              ))}
            </select>
          }
          description="Auto follows the current Windows display."
          title="Display"
        />
        <ControlRow
          action={
            <div className="alignment-buttons" aria-label="Island alignment">
              {(['left', 'center', 'right'] as IslandAlignment[]).map((alignment) => (
                <button
                  aria-pressed={placement.alignment === alignment}
                  className={placement.alignment === alignment ? 'active' : ''}
                  key={alignment}
                  onClick={() => updatePlacement({ ...placement, alignment })}
                  type="button"
                >
                  {alignment}
                </button>
              ))}
            </div>
          }
          description="Place the recessed Island line along the selected display's top edge."
          title="Alignment"
        />
      </ControlSection>

      <ControlSection icon={Sparkles} title="Desktop companion">
        <ControlRow
          action={
            <button
              aria-checked={petPreferences.enabled}
              className={petPreferences.enabled ? 'mode-switch active' : 'mode-switch'}
              onClick={() => updatePet({ ...petPreferences, enabled: !petPreferences.enabled })}
              role="switch"
              type="button"
            >
              {petPreferences.enabled ? 'Visible' : 'Hidden'}
            </button>
          }
          description="Show a click-through companion that mirrors Marvi's live state."
          title="Companion"
        />
        <ControlRow
          action={
            <select
              aria-label="Pet display"
              onChange={(event) =>
                updatePet({
                  ...petPreferences,
                  displayId: event.target.value === 'auto' ? null : Number(event.target.value)
                })
              }
              value={petPreferences.displayId ?? 'auto'}
            >
              <option value="auto">Auto · current</option>
              {displays.map((display) => (
                <option key={display.id} value={display.id}>
                  {display.label}
                  {display.primary ? ' · primary' : ''}
                </option>
              ))}
            </select>
          }
          description="Auto follows the current Windows display."
          title="Display"
        />
        <ControlRow
          action={
            <div className="alignment-buttons" aria-label="Pet side">
              {(['left', 'right'] as PetSide[]).map((side) => (
                <button
                  aria-pressed={petPreferences.side === side}
                  className={petPreferences.side === side ? 'active' : ''}
                  key={side}
                  onClick={() => updatePet({ ...petPreferences, side })}
                  type="button"
                >
                  {side}
                </button>
              ))}
            </div>
          }
          description="Choose which lower corner holds the companion."
          title="Corner"
        />
        <ControlRow
          action={
            <select
              aria-label="Pet size"
              onChange={(event) =>
                updatePet({ ...petPreferences, scale: Number(event.target.value) as PetScale })
              }
              value={petPreferences.scale}
            >
              <option value={0.4}>Tiny · 40%</option>
              <option value={0.5}>Compact · 50%</option>
              <option value={0.7}>Medium · 70%</option>
              <option value={1}>Full · 100%</option>
            </select>
          }
          description="Scale the sprite and its compact control strip together."
          title="Size"
        />
      </ControlSection>
    </ControlPage>
  )
}

function PreferencesPanel({ runtime }: { runtime: RuntimeStatus }): React.JSX.Element {
  const setYolo = (enabled: boolean): void => {
    void window.marvi?.setYolo(enabled).then(applyRuntimeState)
  }

  return (
    <ControlPage
      aria-label="Marvi OS settings"
      className="settings-page"
      description="Manage local services, action approval, and connected devices."
      title="Preferences"
    >
      <ControlSection className="settings-services" icon={Server} title="Runtime">
        <div>
          <p>
            Marvi starts these itself. When one will not start, the reason is its own output — shown
            here rather than discarded.
          </p>
        </div>
        <ServiceHealth compact />
      </ControlSection>

      <ControlSection icon={ShieldAlert} title="Confirmation mode">
        <ControlRow
          action={
            <button
              aria-checked={runtime.assistant.yolo}
              className={runtime.assistant.yolo ? 'mode-switch active' : 'mode-switch'}
              onClick={() => setYolo(!runtime.assistant.yolo)}
              role="switch"
              type="button"
            >
              {runtime.assistant.yolo ? 'YOLO · auto accept' : 'Confirm · ask me'}
            </button>
          }
          description="Confirm asks before actions when the model decides approval is needed. YOLO bypasses every prompt."
          title="Action approval"
        />
      </ControlSection>

      <ControlSection icon={Gauge} title="Device status">
        <ControlRow
          action={<ControlPill>{DEVICE_COPY[deviceState(runtime, 'microphone')]}</ControlPill>}
          title="Microphone"
        />
        <ControlRow
          action={<ControlPill>{DEVICE_COPY[deviceState(runtime, 'camera')]}</ControlPill>}
          title="Camera"
        />
        <ControlRow
          action={<ControlPill tone={stateTone(runtime.state)}>{runtime.state}</ControlPill>}
          title="Gateway"
        />
      </ControlSection>
    </ControlPage>
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
    <ControlPage className="about-control-page" title="About">
      <div className="control-about-identity">
        <BrandIcon className="brand-icon-about" />
        <div>
          <h2>Marvi OS</h2>
          <p>Local voice and vision assistant for Windows</p>
        </div>
      </div>

      <ControlSection icon={Info} title="Build information">
        {facts.map(([label, value]) => (
          <ControlRow
            action={<span className="control-value">{value}</span>}
            key={label}
            title={label.toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase())}
          />
        ))}
      </ControlSection>

      <ControlSection icon={Activity} title="Updates">
        <AboutUpdates version={build.version} />
      </ControlSection>

      <ControlSection icon={Wrench} title="Support">
        <ControlRow
          action={
            <ControlButton onClick={() => void window.marvi?.copyDiagnostics()}>
              Copy diagnostics
            </ControlButton>
          }
          description="Copies a redacted local report for troubleshooting."
          title="Diagnostics"
        />
      </ControlSection>
    </ControlPage>
  )
}

function IslandSurface(): React.JSX.Element {
  const voice = useStore($voiceState)
  const measureRef = useRef<HTMLDivElement>(null)
  const [resolvingToken, setResolvingToken] = useState<string | null>(null)

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
          confirmationPending={resolvingToken === voice.confirmation?.token}
          onConfirmationDecision={async (decision) => {
            if (!voice.confirmation || resolvingToken === voice.confirmation.token) return
            const token = voice.confirmation.token
            setResolvingToken(token)
            try {
              const next = await window.marvi?.resolveConfirmation(token, decision)
              if (next) applyRuntimeState(next)
            } finally {
              setResolvingToken(null)
            }
          }}
          state={voice}
        />
      </div>
    </div>
  )
}

/**
 * Saying her name joins, exactly as pressing Join does.
 *
 * Two ways in, because the listener fires against whichever Marvi exists at
 * the time. If she was already open, the main process forwards the event and
 * this window hears it. If the listener started her, the event happened before
 * any window existed, so the launch flag carries it instead — consumed rather
 * than read, or every navigation would rejoin.
 */
function useWakeJoin(): void {
  useEffect(() => {
    void (async () => {
      if (await window.marvi?.consumeWakeLaunch()) void startVoice()
    })()
    return window.marvi?.onWakeJoin(() => void startVoice())
  }, [])
}

export default function App(): React.JSX.Element {
  const surface = new URLSearchParams(window.location.search).get('surface')
  if (surface === 'island') return <IslandSurface />
  return (
    <TooltipProvider>
      <HapticsProvider>
        <WakeJoin />
        <MainSurface />
      </HapticsProvider>
    </TooltipProvider>
  )
}

/** Only on the main surface. The island loads the same bundle, and both
 *  windows racing to consume the launch flag would join in the wrong one. */
function WakeJoin(): null {
  useWakeJoin()
  return null
}
