/**
 * How Marvi is, right now, in one picture.
 *
 * The page this replaces was three checklists: a hero, a route, a list of
 * services and a list of context values. Every one of them was true and the
 * page still could not answer the question people open it with, because that
 * question is not "are the processes up" -- it is "is she alright, and is she
 * going to say anything". Those come apart constantly and did all week: every
 * service green, the mind turning happily, and nothing reaching anybody
 * because a gate had closed or a feeder had quietly stopped feeding.
 *
 * So there are two paths drawn here, not one. The **answering** path is what
 * happens when you talk to her -- microphone, LiveKit, Gateway, voice. The
 * **noticing** path is what happens when nobody does -- feeders, the mind, the
 * announcer. The old page drew the first and had no idea the second existed,
 * which is exactly the half that was broken.
 */
import { Ear, Inbox, Megaphone, Mic, Radio, Server, Sparkles } from 'lucide-react'
import React, { useEffect, useState } from 'react'

import type {
  DeviceState,
  InitiativeStatus,
  ResourceState,
  RuntimeStatus
} from '../../../shared/runtime'
import type { VoiceState } from '../store/voice-state'

type Tone = 'neutral' | 'ready' | 'warning' | 'danger'

function toneOf(state: string | undefined): Tone {
  if (state === 'ready' || state === 'connected' || state === 'active' || state === 'running') {
    return 'ready'
  }
  if (state === 'error' || state === 'failed' || state === 'offline' || state === 'stopped') {
    return 'danger'
  }
  if (state === 'pending' || state === 'starting' || state === 'degraded') return 'warning'
  return 'neutral'
}

const DEVICE_WORDS: Record<DeviceState, string> = {
  on: 'always on',
  off: 'off',
  unknown: 'unknown'
}

/**
 * A component's status, in words rather than in its own vocabulary.
 *
 * These strings are written for a log: "sidecar connected on 127.0.0.1:7842",
 * "local facade online". On a tile they are worse than useless -- the part
 * that carries the meaning is the first word and the part that gets truncated
 * is everything after it, so the tile read `sidecar connected on 127.0....`
 * and told you nothing you could not see from the dot beside it.
 *
 * The mapping is deliberately shallow. Anything unrecognised is passed through
 * whole, because inventing a friendlier phrase for a status this does not know
 * would be inventing a fact.
 */
function plainly(detail: string | undefined, fallback: string): string {
  const text = (detail ?? '').trim()
  if (!text) return fallback
  if (/^sidecar connected/i.test(text)) return 'connected'
  if (/^local facade online/i.test(text)) return 'running here'
  if (/^livekit up/i.test(text)) return 'ready'
  // "Smart Room camera online, 2 visible, Shereef" -> "camera on, 2 visible".
  const camera = /^smart room camera online,\s*(.+?)(?:,\s*[^,]*)?$/i.exec(text)
  if (camera) return `camera on, ${camera[1]}`
  return text
}

function Hop({ label, tone }: { label: string; tone: Tone }): React.JSX.Element {
  return (
    <span className={`ovp-hop tone-${tone}`}>
      <i aria-hidden="true" />
      {label}
    </span>
  )
}

export function OverviewPage({
  runtime,
  voice,
  device,
  onOpenMind
}: {
  runtime: RuntimeStatus
  voice: VoiceState
  /** `deviceState` from the shell, so both pages agree about the microphone. */
  device: (which: 'microphone' | 'camera') => DeviceState
  onOpenMind: () => void
}): React.JSX.Element {
  const [mind, setMind] = useState<InitiativeStatus | null>(null)
  const [resources, setResources] = useState<ResourceState | null>(null)

  useEffect(() => {
    let gone = false
    const load = async (): Promise<void> => {
      const [status, found] = await Promise.all([
        window.marvi?.getInitiative(),
        window.marvi?.getResources()
      ])
      if (gone) return
      if (status) setMind(status)
      if (found) setResources(found)
    }
    void load()
    const timer = setInterval(() => {
      if (!document.hidden) void load()
    }, 10_000)
    return () => {
      gone = true
      clearInterval(timer)
    }
  }, [])

  const services = [
    { label: 'Gateway', service: runtime.components.gateway },
    { label: 'LiveKit', service: runtime.components.livekit },
    { label: 'Voice', service: runtime.components.voice },
    { label: 'Room', service: runtime.components.room },
    { label: 'Accounts', service: runtime.components.accounts }
  ]
  const ready = services.filter(({ service }) => toneOf(service?.state) === 'ready').length
  const unwell = services.filter(({ service }) => toneOf(service?.state) === 'danger')

  const quiet = mind?.quiet_because ?? ''
  const waiting = mind?.waiting ?? []
  const feeders = mind?.feeders ?? []
  // Wired and producing nothing: the failure that hides, because every other
  // indicator on this page reads perfectly healthy while it is happening.
  const mute = feeders.filter((feeder) => feeder.wired && feeder.events === 0)

  return (
    <div className="ovp-page">
      {/* One sentence about her, not five about the processes. */}
      <section className={`ovp-hero tone-${toneOf(runtime.state)}`}>
        <div className="ovp-hero-main">
          <Sparkles aria-hidden="true" />
          <div>
            <h2>{voice.caption}</h2>
            <p>{voice.detail ?? 'Standing by for voice, context, or scheduled work.'}</p>
          </div>
        </div>
        <button className="ovp-hero-mind" onClick={onOpenMind} type="button">
          <span className={quiet ? 'ovp-mind-dot is-quiet' : 'ovp-mind-dot'} />
          {quiet ? `Quiet — ${quiet}` : 'Listening for anything worth saying'}
        </button>
      </section>

      {unwell.length > 0 && (
        <p className="ovp-trouble">
          {unwell.map(({ label }) => label).join(', ')} {unwell.length === 1 ? 'is' : 'are'} not
          answering.
        </p>
      )}

      {/* The two paths. The old page drew the first and had no idea the
          second existed, which is exactly the half that was broken. */}
      <div className="ovp-paths">
        <section className="ovp-path">
          <h3>
            <Mic aria-hidden="true" /> When you talk to her
          </h3>
          <div className="ovp-flow">
            <Hop label="Microphone" tone={device('microphone') === 'on' ? 'ready' : 'danger'} />
            <Hop label="LiveKit" tone={toneOf(runtime.components.livekit?.state)} />
            <Hop label="Gateway" tone={toneOf(runtime.components.gateway?.state)} />
            <Hop label="Voice" tone={toneOf(runtime.components.voice?.state)} />
          </div>
          <p className="ovp-path-note">
            {runtime.model.llm || 'Automatic model'} ·{' '}
            {voice.yolo ? 'acts without asking' : 'asks first'}
          </p>
        </section>

        <section className="ovp-path">
          <h3>
            <Radio aria-hidden="true" /> When nobody does
          </h3>
          <div className="ovp-flow">
            <Hop
              label={`${feeders.filter((one) => one.wired).length} sources`}
              tone={mute.length ? 'warning' : feeders.length ? 'ready' : 'neutral'}
            />
            <Hop label="Mind" tone={mind?.running ? (quiet ? 'warning' : 'ready') : 'danger'} />
            <Hop label="Announcer" tone={quiet ? 'neutral' : 'ready'} />
          </div>
          <p className="ovp-path-note">
            {mute.length
              ? `${mute.map((one) => one.label.toLowerCase()).join(', ')} connected but silent`
              : waiting.length
                ? `${waiting.length} held until it can be said`
                : 'nothing waiting'}
          </p>
        </section>
      </div>

      {waiting.length > 0 && (
        <p className="ovp-waiting">
          <Inbox aria-hidden="true" />
          {waiting[0].summary} — held because {waiting[0].because || waiting[0].reason}
        </p>
      )}

      {resources?.low_resource && (
        <p className="ovp-resources">
          <Megaphone aria-hidden="true" />
          Standing down off the GPU while {resources.because} is running.
        </p>
      )}

      <section className="ovp-context">
        <h3>
          <Ear aria-hidden="true" /> What she can see and hear
        </h3>
        <div className="ovp-tiles">
          {[
            {
              label: 'Room',
              value: plainly(runtime.components.room?.detail, 'offline'),
              raw: runtime.components.room?.detail,
              tone: toneOf(runtime.components.room?.state)
            },
            {
              label: 'Vision',
              value: plainly(runtime.components.vision?.detail, 'offline'),
              raw: runtime.components.vision?.detail,
              tone: toneOf(runtime.components.vision?.state)
            },
            {
              label: 'Accounts',
              value: plainly(runtime.components.accounts?.detail, 'none connected'),
              raw: runtime.components.accounts?.detail,
              tone: toneOf(runtime.components.accounts?.state)
            },
            {
              label: 'Microphone',
              value: DEVICE_WORDS[device('microphone')],
              raw: undefined,
              tone: device('microphone') === 'on' ? ('ready' as Tone) : ('neutral' as Tone)
            },
            {
              label: 'Camera',
              value: DEVICE_WORDS[device('camera')],
              raw: undefined,
              tone: device('camera') === 'on' ? ('ready' as Tone) : ('neutral' as Tone)
            }
          ].map((tile) => (
            <div className={`ovp-tile tone-${tile.tone}`} key={tile.label}>
              <span>
                <i aria-hidden="true" />
                {tile.label}
              </span>
              {/* The exact wording stays reachable on hover: shortening it for
                  reading should not mean losing the address when something is
                  wrong with it. */}
              <strong title={tile.raw ?? tile.value}>{tile.value}</strong>
            </div>
          ))}
        </div>
      </section>

      {/* Last, and small. It is the answer to a question people ask when
          something else has already told them to. */}
      <section className="ovp-systems">
        <h3>
          <Server aria-hidden="true" /> Systems
          <span>
            {ready} of {services.length} ready
          </span>
        </h3>
        <ul>
          {services.map(({ label, service }) => (
            <li className={`tone-${toneOf(service?.state)}`} key={label}>
              <i aria-hidden="true" />
              <span>{label}</span>
              <small title={service?.detail ?? ''}>
                {plainly(service?.detail, 'no status received')}
              </small>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
