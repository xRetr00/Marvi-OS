import { useStore } from '@nanostores/react'
import { useEffect, useState } from 'react'

import { DynamicIsland } from './components/DynamicIsland'
import { $voiceState, VOICE_PHASES, cycleVoicePhase, type VoicePhase } from './store/voice-state'

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

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <header className="brand-block">
          <div className="ascii-mark" aria-hidden="true">
            [ M ]
          </div>
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

function IslandSurface(): React.JSX.Element {
  const voice = useStore($voiceState)
  return (
    <button
      className="island-stage"
      onDoubleClick={() => window.marvi.showMain()}
      title="Double-click to open Marvi OS"
    >
      <DynamicIsland state={voice} />
    </button>
  )
}

export default function App(): React.JSX.Element {
  const surface = new URLSearchParams(window.location.search).get('surface')
  return surface === 'island' ? <IslandSurface /> : <MainSurface />
}
