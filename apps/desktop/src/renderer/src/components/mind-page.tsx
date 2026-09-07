/**
 * The Mind, as something you can look into rather than a list of counters.
 *
 * The page this replaces had a pause button, three numbers and a flat log of
 * decisions, and it could not answer the only question anybody opens it with:
 * *why has she not said anything?* The machinery was turning, the counters
 * were fine, and the reason was somewhere else entirely -- a feeder that had
 * silently stopped feeding, a gate that closes every night at eleven, a
 * summary waiting on a rate-limited model.
 *
 * So this is laid out as the path a signal actually takes:
 *
 *     feeders  ->  journal  ->  salience  ->  gates  ->  surface
 *
 * Every element carries live data and nothing here is decoration. A feeder
 * that is wired and silent is drawn differently from one that is not wired.
 * A gate that is currently closed says which one and why. The waiting room
 * shows what is being held and how long it has waited. The decision stream
 * shows where each event stopped on that path, which is the shape of the
 * answer to "why was that not said out loud".
 */
import {
  Activity,
  Brain,
  Cpu,
  Ear,
  Gamepad2,
  History,
  Inbox,
  Loader,
  Pause,
  Play,
  Timer
} from 'lucide-react'
import React, { useEffect, useMemo, useState } from 'react'

import type { Feeder, InitiativeStatus, MindDecision, WaitingItem } from '../../../shared/runtime'

/** Every hour, for the quiet-hours pickers. */
const HOURS = Array.from({ length: 24 }, (_, hour) => hour)

/** The surfaces, quietest first. Mirrors `policy.SURFACES` exactly. */
const LADDER = ['silent', 'remember', 'activity', 'island', 'speak', 'propose'] as const

/** What each surface means, in the words a person would use. */
const LADDER_MEANS: Record<string, string> = {
  silent: 'noticed, nothing done',
  remember: 'written down',
  activity: 'in the feed',
  island: 'on the island',
  speak: 'said out loud',
  propose: 'offered as an action'
}

const FEEDER_ICON: Record<string, typeof Ear> = {
  room: Ear,
  machine: Cpu,
  focus: Gamepad2,
  accounts: Inbox,
  schedule: Timer
}

/** Every gate in `policy.evaluate`, in the order it applies them. */
const GATES: { id: string; label: string; explains: string }[] = [
  { id: 'initiative is switched off', label: 'Initiative', explains: 'you turned her off' },
  { id: 'quiet hours', label: 'Quiet hours', explains: 'the small hours' },
  { id: 'you are in a call', label: 'Foreground', explains: 'the call owns the voice' },
  { id: 'nobody seems to be here', label: 'Presence', explains: 'nobody to hear it' },
  { id: 'is running', label: 'Resources', explains: 'a game has the machine' },
  { id: "the day's thinking", label: 'Budget', explains: "the day's thinking is spent" }
]

function humanGap(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${Math.round(seconds / 3600)}h`
}

/**
 * The gate currently holding her quiet, matched from the reason the Gateway
 * gives. Substring rather than an enum because the reason carries the detail
 * with it -- "quiet hours, until 08:00" -- and losing that to a tidy code
 * would make the panel less useful than the sentence it came from.
 */
function closedGate(reason: string): string | null {
  if (!reason) return null
  const found = GATES.find((gate) => reason.includes(gate.id))
  return found ? found.label : 'Other'
}

function MindDiagram({
  feeders,
  decisions,
  quietBecause,
  waiting
}: {
  feeders: Feeder[]
  decisions: MindDecision[]
  quietBecause: string
  waiting: number
}): React.JSX.Element {
  // Where recent events actually stopped. This is the whole point of the
  // drawing: a tall bar on `silent` and nothing on `speak` is a mind working
  // perfectly and never reaching anybody.
  const reached = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const decision of decisions) {
      counts[decision.surface] = (counts[decision.surface] ?? 0) + 1
    }
    return counts
  }, [decisions])

  const most = Math.max(1, ...Object.values(reached))
  const blocked = closedGate(quietBecause)
  const rows = feeders.length || 1
  const height = Math.max(210, rows * 34 + 70)

  return (
    <svg
      aria-label="How a signal travels through the mind"
      className="mind-diagram"
      role="img"
      viewBox={`0 0 720 ${height}`}
    >
      <defs>
        <linearGradient id="mind-flow" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="var(--ui-accent)" stopOpacity="0.05" />
          <stop offset="0.5" stopColor="var(--ui-accent)" stopOpacity="0.4" />
          <stop offset="1" stopColor="var(--ui-accent)" stopOpacity="0.05" />
        </linearGradient>
      </defs>

      {/* Feeders, and the line each one sends into the journal. A wired
          feeder that has produced nothing is drawn dashed: connected, and
          silently not feeding, which is the failure that hides. */}
      {feeders.map((feeder, index) => {
        const y = 44 + index * 34
        const silent = feeder.wired && feeder.events === 0
        return (
          <g key={feeder.id}>
            <text className="mind-diagram-label" x="0" y={y + 4}>
              {feeder.label}
            </text>
            <path
              className={
                !feeder.wired
                  ? 'mind-edge is-off'
                  : silent
                    ? 'mind-edge is-silent'
                    : 'mind-edge is-live'
              }
              d={`M 150 ${y} C 190 ${y}, 200 ${height / 2}, 240 ${height / 2}`}
              fill="none"
            />
            <circle
              className={
                feeder.wired ? (silent ? 'mind-dot is-silent' : 'mind-dot') : 'mind-dot is-off'
              }
              cx="144"
              cy={y}
              r="3"
            />
            <text className="mind-diagram-count" x="158" y={y - 6}>
              {feeder.wired ? feeder.events || '—' : 'off'}
            </text>
          </g>
        )
      })}

      {/* The middle: everything funnels through one gate stack. */}
      <rect
        className={blocked ? 'mind-gate is-closed' : 'mind-gate'}
        height="46"
        rx="6"
        width="120"
        x="240"
        y={height / 2 - 23}
      />
      <text className="mind-diagram-node" textAnchor="middle" x="300" y={height / 2 - 4}>
        {blocked ? 'held' : 'open'}
      </text>
      <text className="mind-diagram-sub" textAnchor="middle" x="300" y={height / 2 + 11}>
        {blocked ?? 'all gates open'}
      </text>
      {waiting > 0 && (
        <text className="mind-diagram-waiting" textAnchor="middle" x="300" y={height / 2 + 38}>
          {waiting} waiting
        </text>
      )}

      <path
        className={blocked ? 'mind-edge is-silent' : 'mind-edge is-live'}
        d={`M 360 ${height / 2} L 430 ${height / 2}`}
        fill="none"
      />

      {/* The ladder, with how many recent events reached each rung. */}
      {LADDER.map((surface, index) => {
        const y = 30 + index * 26
        const count = reached[surface] ?? 0
        const width = count ? Math.max(6, (count / most) * 150) : 0
        return (
          <g key={surface}>
            <rect
              className={
                surface === 'speak' || surface === 'propose' ? 'mind-bar is-loud' : 'mind-bar'
              }
              height="14"
              rx="3"
              width={width}
              x="440"
              y={y - 10}
            />
            <text className="mind-diagram-rung" x={440 + width + 6} y={y}>
              {surface}
              {count > 0 ? ` · ${count}` : ''}
            </text>
          </g>
        )
      })}
      <line className="mind-axis" x1="438" x2="438" y1="14" y2={30 + LADDER.length * 26 - 20} />
    </svg>
  )
}

export function MindPage(): React.JSX.Element {
  const [status, setStatus] = useState<InitiativeStatus | null>(null)
  const [decisions, setDecisions] = useState<MindDecision[]>([])
  const [reload, setReload] = useState(0)
  const [busy, setBusy] = useState(false)

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

  /** One knob at a time, and the answer is the new status. */
  const setQuiet = async (patch: Record<string, number | boolean>): Promise<void> => {
    const next = await window.marvi?.setMindSettings(patch)
    if (next) setStatus(next)
    else setReload((n) => n + 1)
  }

  const toggle = async (): Promise<void> => {
    setBusy(true)
    await window.marvi?.setInitiative(!(status?.paused ?? false))
    setBusy(false)
    setReload((n) => n + 1)
  }

  const feeders = status?.feeders ?? []
  const waiting: WaitingItem[] = status?.waiting ?? []
  const quiet = status?.quiet_because ?? ''
  const errors = Object.entries(status?.last_errors ?? {})
  const paused = status?.paused ?? false

  return (
    <div className="mind-page">
      <header className="mind-head">
        <div className="mind-head-copy">
          <h2>Mind</h2>
          <p>
            What reaches her, what stops it, and what is still waiting to be said. Everything on
            this page is live.
          </p>
        </div>
        <button className="mind-toggle" disabled={busy} onClick={() => void toggle()} type="button">
          {busy ? (
            <Loader aria-hidden="true" className="is-spinning" />
          ) : paused ? (
            <Play aria-hidden="true" />
          ) : (
            <Pause aria-hidden="true" />
          )}
          {paused ? 'Resume' : 'Pause'}
        </button>
      </header>

      {/* The one sentence the old page could not produce. */}
      <div className={quiet ? 'mind-state is-quiet' : 'mind-state'}>
        <span className="mind-state-dot" />
        <strong>{quiet ? 'Quiet' : 'Listening'}</strong>
        <span className="mind-state-why">{quiet || 'nothing is holding her back right now'}</span>
        <span className="mind-state-meta">
          {status?.running ? 'scheduler running' : 'scheduler stopped'} ·{' '}
          {status?.pending_events ?? 0} unread events
        </span>
      </div>

      <section className="mind-block">
        <MindDiagram
          decisions={decisions}
          feeders={feeders}
          quietBecause={quiet}
          waiting={waiting.length}
        />
      </section>

      <div className="mind-columns">
        <section className="mind-block">
          <h3>
            <Activity aria-hidden="true" /> Gates
          </h3>
          <p className="mind-block-sub">
            Every event is checked against these in order. The closed one is the reason.
          </p>
          {/* Quiet hours, reachable.
              The Gateway has accepted these since they were written and
              nothing in the app ever sent them, so the one gate that closes on
              a schedule was a constant somebody would have had to edit an env
              file to change -- and could only switch off by setting its two
              ends to the same hour, which is a trick rather than a setting. */}
          <div className="mind-quiet">
            <label className="mind-quiet-on">
              <input
                checked={Boolean(status?.settings?.quiet_enabled ?? true)}
                onChange={(event) => void setQuiet({ quiet_enabled: event.target.checked })}
                type="checkbox"
              />
              <span>Quiet hours</span>
            </label>
            <div className={status?.settings?.quiet_enabled === false ? 'is-off' : ''}>
              <label>
                <span>from</span>
                <select
                  disabled={status?.settings?.quiet_enabled === false}
                  onChange={(event) => void setQuiet({ quiet_start: Number(event.target.value) })}
                  value={Number(status?.settings?.quiet_start ?? 23)}
                >
                  {HOURS.map((hour) => (
                    <option key={hour} value={hour}>
                      {String(hour).padStart(2, '0')}:00
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>until</span>
                <select
                  disabled={status?.settings?.quiet_enabled === false}
                  onChange={(event) => void setQuiet({ quiet_end: Number(event.target.value) })}
                  value={Number(status?.settings?.quiet_end ?? 8)}
                >
                  {HOURS.map((hour) => (
                    <option key={hour} value={hour}>
                      {String(hour).padStart(2, '0')}:00
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <p>
              {status?.settings?.quiet_enabled === false
                ? 'Off — she may speak at any hour.'
                : 'She still notices things; she writes them down instead of saying them.'}
            </p>
          </div>

          {/* Repeats, reachable for the same reason quiet hours are.
              The journal drops an event whose source, kind, summary and
              payload match one from the last six hours. That is right nearly
              always -- a mailbox re-reporting the same message every poll is
              one event, not forty -- and wrong exactly when the repeat *is*
              the news. It swallowed a second FC 26 launch two hours after the
              first, and seven of eight presses of Run Now on one reminder.
              Both are fixed where they happen; this is for the ones nobody
              has hit yet, because the failure is silence and silence is not
              findable from outside. */}
          <div className="mind-quiet">
            <label className="mind-quiet-on">
              <input
                checked={Boolean(status?.settings?.dedupe_events ?? true)}
                onChange={(event) => void setQuiet({ dedupe_events: event.target.checked })}
                type="checkbox"
              />
              <span>Ignore repeats</span>
            </label>
            <p>
              {status?.settings?.dedupe_events === false
                ? 'Off — she treats every event as news, even one she has already had. Noisier, and nothing is lost.'
                : 'The same event twice within six hours counts once. Switch this off if you would rather hear a thing twice than miss it.'}
            </p>
          </div>

          <ul className="mind-gates">
            {GATES.map((gate) => {
              const shut = quiet.includes(gate.id)
              return (
                <li className={shut ? 'is-shut' : ''} key={gate.id}>
                  <span className="mind-gate-lamp" />
                  <span className="mind-gate-name">{gate.label}</span>
                  <span className="mind-gate-why">{shut ? quiet : gate.explains}</span>
                </li>
              )
            })}
          </ul>
        </section>

        <section className="mind-block">
          <h3>
            <Inbox aria-hidden="true" /> Waiting to be said
          </h3>
          <p className="mind-block-sub">
            Held because it could not be said yet, not because it stopped mattering.
          </p>
          {waiting.length === 0 ? (
            <p className="mind-empty">Nothing is waiting.</p>
          ) : (
            <ul className="mind-waiting">
              {waiting.map((item) => (
                <li key={`${item.summary}-${item.waited_seconds}`}>
                  <span className="mind-waiting-what">{item.summary}</span>
                  <span className="mind-waiting-why">
                    {item.because || item.reason} · held {humanGap(item.waited_seconds)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="mind-block">
        <h3>
          <Brain aria-hidden="true" /> What she watches
        </h3>
        <p className="mind-block-sub">
          Events each source produced this week. Wired and silent is the one worth looking at.
        </p>
        <ul className="mind-feeders">
          {feeders.map((feeder) => {
            const Icon = FEEDER_ICON[feeder.id] ?? Activity
            const silent = feeder.wired && feeder.events === 0
            return (
              <li className={!feeder.wired ? 'is-off' : silent ? 'is-silent' : ''} key={feeder.id}>
                <Icon aria-hidden="true" />
                <span className="mind-feeder-name">{feeder.label}</span>
                <span className="mind-feeder-count">
                  {!feeder.wired
                    ? 'not connected'
                    : silent
                      ? 'nothing this week'
                      : `${feeder.events}`}
                </span>
                {/* What those events were. "This machine: 2" is a number with
                    nothing behind it, and the page could not answer the
                    obvious next question. */}
                {(feeder.examples ?? []).length > 0 && (
                  <ul className="mind-feeder-examples">
                    {(feeder.examples ?? []).map((example) => (
                      <li key={example}>{example}</li>
                    ))}
                  </ul>
                )}
              </li>
            )
          })}
        </ul>
      </section>

      {errors.length > 0 && (
        <section className="mind-block">
          <h3>Trouble</h3>
          <ul className="mind-errors">
            {errors.map(([job, error]) => (
              <li key={job}>
                <span className="mind-error-job">{job.replaceAll('_', ' ')}</span>
                <span className="mind-error-detail">{String(error).slice(0, 200)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mind-block">
        <h3>
          <History aria-hidden="true" /> Decisions
        </h3>
        <p className="mind-block-sub">Where each event stopped, and what it cost to decide.</p>
        {decisions.length === 0 ? (
          <p className="mind-empty">Nothing has reached the policy yet.</p>
        ) : (
          <ul className="mind-stream">
            {decisions.map((decision) => (
              <li key={decision.id}>
                <span className="mind-stream-time">{decision.at.slice(11, 19)}</span>
                <span className="mind-stream-trigger">{decision.trigger.replaceAll('_', ' ')}</span>
                <span className="mind-stream-rungs" title={LADDER_MEANS[decision.surface] ?? ''}>
                  {LADDER.map((surface) => (
                    <i
                      className={
                        surface === decision.surface
                          ? 'is-here'
                          : LADDER.indexOf(surface) < LADDER.indexOf(decision.surface as never)
                            ? 'is-passed'
                            : ''
                      }
                      key={surface}
                    />
                  ))}
                </span>
                <span className="mind-stream-surface">{decision.surface}</span>
                <span className="mind-stream-rule">{decision.detail || decision.rule}</span>
                <span className="mind-stream-cost">
                  {decision.provider === 'deterministic'
                    ? 'no model'
                    : decision.provider.split('/')[0]}{' '}
                  · {decision.latency_ms.toFixed(0)}ms
                  {decision.said_ms && decision.said_ms > 500
                    ? ` · spoke ${(decision.said_ms / 1000).toFixed(1)}s`
                    : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
