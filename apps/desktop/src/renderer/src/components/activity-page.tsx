/**
 * Every tool Marvi has reached for, and how it went.
 *
 * The page this replaces printed one row per event with the arguments
 * `JSON.stringify`d into the subtitle, which meant the interesting rows -- the
 * refusals, the failures, the thing she did without asking -- were the same
 * shape and colour as the eighty routine ones above them. You could read it,
 * but only by reading all of it.
 *
 * So the top of the page answers the questions first: how much has she done,
 * how much of it failed, how much went through without a confirmation. Then
 * the stream, with outcome carried in colour, arguments folded away until
 * asked for, and repeated calls to the same tool collapsed into one row you
 * can open -- because "she called room_set_light eleven times" is one fact,
 * not eleven.
 */
import {
  AlertTriangle,
  Check,
  ChevronRight,
  CircleSlash,
  Clock3,
  Filter,
  History,
  Zap
} from 'lucide-react'
import React, { useEffect, useMemo, useState } from 'react'

import type { AuditEvent } from '../../../shared/runtime'

type Outcome = 'ok' | 'failed' | 'refused' | 'other'

/** Which of four buckets an event falls in, from its `event` string. */
function outcomeOf(event: AuditEvent): Outcome {
  const name = event.event.toLowerCase()
  if (name.includes('fail') || name.includes('error')) return 'failed'
  if (name.includes('refus') || name.includes('den') || name.includes('reject')) return 'refused'
  if (name.includes('ok') || name.includes('complet') || name.includes('approv')) return 'ok'
  return 'other'
}

const OUTCOME_ICON: Record<Outcome, typeof Check> = {
  ok: Check,
  failed: AlertTriangle,
  refused: CircleSlash,
  other: ChevronRight
}

/** One tool, called one or more times in a row. */
interface Run {
  key: string
  tool: string
  events: AuditEvent[]
  worst: Outcome
  yolo: number
}

/**
 * Consecutive calls to the same tool, collapsed.
 *
 * Only consecutive: two runs of the same tool an hour apart are two things
 * that happened, and merging them would lose the shape of the day. The worst
 * outcome in a run is the one shown, because a run of eleven where one failed
 * is a run that failed.
 */
function runsOf(events: AuditEvent[]): Run[] {
  const runs: Run[] = []
  const rank: Record<Outcome, number> = { ok: 0, other: 1, refused: 2, failed: 3 }
  for (const event of events) {
    const last = runs[runs.length - 1]
    const outcome = outcomeOf(event)
    if (last && last.tool === event.tool) {
      last.events.push(event)
      if (rank[outcome] > rank[last.worst]) last.worst = outcome
      if (event.mode === 'yolo') last.yolo += 1
      continue
    }
    runs.push({
      key: `${event.at}-${event.tool}-${runs.length}`,
      tool: event.tool,
      events: [event],
      worst: outcome,
      yolo: event.mode === 'yolo' ? 1 : 0
    })
  }
  return runs
}

/** Calls per hour over the window, for the strip along the top. */
function byHour(events: AuditEvent[]): { hour: string; total: number; bad: number }[] {
  const buckets = new Map<string, { total: number; bad: number }>()
  for (const event of events) {
    const hour = event.at.slice(0, 13)
    const found = buckets.get(hour) ?? { total: 0, bad: 0 }
    found.total += 1
    if (outcomeOf(event) === 'failed') found.bad += 1
    buckets.set(hour, found)
  }
  return [...buckets.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([hour, counts]) => ({ hour, ...counts }))
}

export function ActivityPage(): React.JSX.Element {
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [only, setOnly] = useState<Outcome | 'all'>('all')
  const [open, setOpen] = useState<string | null>(null)

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

  // Newest first: the thing you came to look at almost always just happened.
  const ordered = useMemo(() => [...events].reverse(), [events])
  const shown = useMemo(
    () => (only === 'all' ? ordered : ordered.filter((event) => outcomeOf(event) === only)),
    [ordered, only]
  )
  const runs = useMemo(() => runsOf(shown), [shown])
  const hours = useMemo(() => byHour(events), [events])

  const failed = events.filter((event) => outcomeOf(event) === 'failed').length
  const unasked = events.filter((event) => event.mode === 'yolo').length
  const tools = new Set(events.map((event) => event.tool)).size
  const busiest = Math.max(1, ...hours.map((hour) => hour.total))

  return (
    <div className="act-page">
      <header className="act-head">
        <div>
          <h2>Activity</h2>
          <p>
            Every tool Marvi reached for, and how it went. Local only — none of this is uploaded.
          </p>
        </div>
      </header>

      <div className="act-figures">
        <div className="act-figure">
          <strong>{events.length}</strong>
          <span>calls</span>
        </div>
        <div className={failed ? 'act-figure is-bad' : 'act-figure'}>
          <strong>{failed}</strong>
          <span>failed</span>
        </div>
        <div className={unasked ? 'act-figure is-warn' : 'act-figure'}>
          <strong>{unasked}</strong>
          <span>without asking</span>
        </div>
        <div className="act-figure">
          <strong>{tools}</strong>
          <span>different tools</span>
        </div>
      </div>

      {/* When she was busy, and when things went wrong. Bars are calls per
          hour; the red portion is the failures inside that hour, so a bad
          patch is visible without reading a single row. */}
      {hours.length > 1 && (
        <div className="act-strip" role="img" aria-label="Tool calls per hour">
          {hours.map((hour) => (
            <div
              className="act-strip-bar"
              key={hour.hour}
              title={`${hour.hour.slice(11)}:00 · ${hour.total} calls, ${hour.bad} failed`}
            >
              <i style={{ height: `${((hour.total - hour.bad) / busiest) * 100}%` }} />
              {hour.bad > 0 && (
                <i className="is-bad" style={{ height: `${(hour.bad / busiest) * 100}%` }} />
              )}
            </div>
          ))}
        </div>
      )}

      <div className="act-filters">
        <Filter aria-hidden="true" />
        {(['all', 'ok', 'failed', 'refused'] as const).map((choice) => (
          <button
            className={only === choice ? 'is-on' : ''}
            key={choice}
            onClick={() => setOnly(choice)}
            type="button"
          >
            {choice === 'all' ? 'Everything' : choice}
          </button>
        ))}
      </div>

      {runs.length === 0 ? (
        <p className="act-empty">
          <Clock3 aria-hidden="true" />
          {events.length === 0
            ? 'Nothing yet. Tool requests and their outcomes appear here.'
            : 'Nothing matches that filter.'}
        </p>
      ) : (
        <ul className="act-stream">
          {runs.map((run) => {
            const first = run.events[0]
            const Icon = OUTCOME_ICON[run.worst]
            const expanded = open === run.key
            return (
              <li className={`act-run is-${run.worst}`} key={run.key}>
                <button
                  aria-expanded={expanded}
                  className="act-run-head"
                  onClick={() => setOpen(expanded ? null : run.key)}
                  type="button"
                >
                  <span className="act-run-time">{first.at.slice(11, 19)}</span>
                  <Icon aria-hidden="true" className="act-run-icon" />
                  <span className="act-run-tool">{run.tool.replaceAll('_', ' ')}</span>
                  {run.events.length > 1 && (
                    <span className="act-run-times">×{run.events.length}</span>
                  )}
                  {run.yolo > 0 && (
                    <span className="act-run-yolo" title="Ran without a confirmation">
                      <Zap aria-hidden="true" /> unasked
                    </span>
                  )}
                  <span className="act-run-detail">{first.detail ?? first.event}</span>
                  <ChevronRight
                    aria-hidden="true"
                    className={expanded ? 'act-chevron is-open' : 'act-chevron'}
                  />
                </button>
                {expanded && (
                  <div className="act-run-body">
                    {run.events.map((event, index) => (
                      <div className="act-call" key={`${event.at}-${index}`}>
                        <span className="act-call-time">{event.at.slice(11, 19)}</span>
                        <span className={`act-call-event is-${outcomeOf(event)}`}>
                          {event.event}
                        </span>
                        <span className="act-call-mode">{event.mode}</span>
                        {Object.keys(event.arguments).length > 0 && (
                          <pre className="act-call-args">
                            {JSON.stringify(event.arguments, null, 2)}
                          </pre>
                        )}
                        {event.detail && <span className="act-call-detail">{event.detail}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}

      <p className="act-foot">
        <History aria-hidden="true" /> Showing the last {events.length} recorded calls.
      </p>
    </div>
  )
}
