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
import type { RuntimeStatus } from '../../shared/runtime'
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
    ['SMART ROOM', runtime.components.room]
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
          <strong>NOT CONNECTED</strong>
        </div>
        <div className="context-line">
          <span>MEMORY</span>
          <strong>FOUNDATION PENDING</strong>
        </div>
      </article>
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
