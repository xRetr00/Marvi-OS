import { useStore } from '@nanostores/react'
import { useEffect, useRef, useState } from 'react'

import appIcon from './assets/app-icon.png'
import { DynamicIsland } from './components/DynamicIsland'
import {
  $voiceState,
  VOICE_PHASES,
  cycleVoicePhase,
  type VoicePhase,
  type VoiceState
} from './store/voice-state'

const NAV_ITEMS = [
  'Overview',
  'Voice',
  'Vision',
  'Room',
  'Accounts',
  'Memory',
  'Activity',
  'Settings',
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

const SERVICES = [
  { name: 'MARVI GATEWAY', state: 'SCAFFOLD', detail: 'health contract ready' },
  { name: 'LIVEKIT', state: 'PENDING', detail: 'server pin required' },
  { name: 'VOICE', state: 'BENCH', detail: 'Moonshine / Kyutai / VibeVoice' },
  { name: 'SMART ROOM', state: 'LINK', detail: 'external sidecar' }
] as const

function MainSurface(): React.JSX.Element {
  const voice = useStore($voiceState)
  const [page, setPage] = useState<Page>('Overview')
  const [version, setVersion] = useState('0.1.0-dev.0')

  useEffect(() => {
    void window.marvi?.getVersion().then(setVersion)
  }, [])

  useEffect(() => {
    window.marvi?.pushIslandState(voice)
  }, [voice])

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
          <Overview voicePhase={voice.phase} />
        ) : page === 'About' ? (
          <AboutPanel fallbackVersion={version} />
        ) : (
          <PagePanel page={page} version={version} />
        )}

        <footer className="statusbar">
          <span>
            <i className="status-ready" /> UI READY
          </span>
          <span>VOICE {voice.phase.toUpperCase()}</span>
          <span>LOCAL MODE</span>
          <span>YOLO OFF</span>
          <span className="status-version">MARVI OS {version}</span>
        </footer>
      </main>
    </div>
  )
}

function Overview({ voicePhase }: { voicePhase: VoicePhase }): React.JSX.Element {
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
            <strong>{voicePhase.toUpperCase()}</strong>
            <p>Local senses armed. Voice runtime awaits the native Windows model bakeoff.</p>
          </div>
        </div>
        <div className="phase-controls" aria-label="Island preview state">
          {VOICE_PHASES.map((phase) => (
            <button
              className={voicePhase === phase ? 'phase active' : 'phase'}
              key={phase}
              onClick={() => cycleVoicePhase(phase)}
            >
              {phase}
            </button>
          ))}
        </div>
      </article>

      <article className="panel services-panel">
        <div className="panel-label">02 / SYSTEMS</div>
        <div className="service-list">
          {SERVICES.map((service) => (
            <div className="service-row" key={service.name}>
              <span className="service-name">{service.name}</span>
              <span className={`service-state state-${service.state.toLowerCase()}`}>
                {service.state}
              </span>
              <small>{service.detail}</small>
            </div>
          ))}
        </div>
      </article>

      <article className="panel event-panel">
        <div className="panel-label">03 / LIVE CONTEXT</div>
        <div className="context-line">
          <span>ROOM</span>
          <strong>PRESENCE ACTIVE</strong>
        </div>
        <div className="context-line">
          <span>VISION</span>
          <strong>LOCAL / IDLE</strong>
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

function AboutPanel({ fallbackVersion }: { fallbackVersion: string }): React.JSX.Element {
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
    ['GATEWAY', 'scaffold'],
    ['LIVEKIT', 'pending pin'],
    ['STT / TTS', 'native bakeoff pending']
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
    const unsubscribe = window.marvi?.onIslandState((next) => {
      if (isVoiceState(next)) $voiceState.set(next)
    })
    return unsubscribe
  }, [])

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
        <DynamicIsland state={voice} />
      </div>
    </div>
  )
}

function isVoiceState(value: unknown): value is VoiceState {
  if (!value || typeof value !== 'object') return false
  const candidate = value as { phase?: unknown; caption?: unknown; level?: unknown }
  return (
    typeof candidate.phase === 'string' &&
    VOICE_PHASES.includes(candidate.phase as VoicePhase) &&
    typeof candidate.caption === 'string' &&
    typeof candidate.level === 'number'
  )
}

export default function App(): React.JSX.Element {
  const surface = new URLSearchParams(window.location.search).get('surface')
  return surface === 'island' ? <IslandSurface /> : <MainSurface />
}
