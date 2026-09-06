/**
 * Cron jobs as things with a next time, rather than rows in a registry.
 *
 * The list this replaces printed the crontab back at you -- `0 6 * * 1-5` --
 * which is legible to about the same set of people who wrote it, and could not
 * print a next-run time at all: the store only ever computed one for one-off
 * schedules, so `next_run` was null for every repeating job in the app. That
 * is fixed on the Gateway; this is the half that shows it.
 *
 * The order is by when it runs next, because "what is about to happen" is why
 * anybody opens this page. A job that has never run, one that ran and failed
 * and one that is paused are three different states and used to be one grey
 * row each.
 */
import { AlertTriangle, Ban, CalendarDays, Check, Play, Timer, Trash2 } from 'lucide-react'
import React from 'react'

import type { ScheduleRow } from '../../../shared/runtime'
import { saysWhen, untilNext } from './schedule-time'

type Act = 'remove' | 'enable' | 'disable' | 'run'

export function ScheduleCards({
  rows,
  onAct
}: {
  rows: ScheduleRow[]
  onAct: (id: number, action: Act) => void
}): React.JSX.Element {
  // Soonest first, paused last: the page is about what happens next.
  const ordered = [...rows].sort((a, b) => {
    if (a.enabled !== b.enabled) return a.enabled ? -1 : 1
    if (!a.next_run) return 1
    if (!b.next_run) return -1
    return a.next_run.localeCompare(b.next_run)
  })
  const next = ordered.find((row) => row.enabled && row.next_run)

  return (
    <div className="sched-list">
      {next && (
        <p className="sched-next">
          <Timer aria-hidden="true" />
          Next: <strong>{next.name}</strong> {untilNext(next.next_run)}
        </p>
      )}

      {ordered.map((row) => {
        const state = !row.enabled ? 'paused' : row.last_error ? 'failed' : 'on'
        return (
          <article className={`sched-card is-${state}`} key={row.id}>
            <header>
              <span className="sched-name">{row.name}</span>
              <span className={`sched-state is-${state}`}>
                {state === 'paused' ? (
                  <Ban aria-hidden="true" />
                ) : state === 'failed' ? (
                  <AlertTriangle aria-hidden="true" />
                ) : (
                  <Check aria-hidden="true" />
                )}
                {state === 'paused' ? 'Paused' : state === 'failed' ? 'Failed' : 'On'}
              </span>
            </header>

            <div className="sched-when">
              <CalendarDays aria-hidden="true" />
              <span>{saysWhen(row)}</span>
              {row.enabled && row.next_run && (
                <span className="sched-eta">{untilNext(row.next_run)}</span>
              )}
              {row.insist && (
                <span className="sched-insist" title="Speaks through quiet hours">
                  insists
                </span>
              )}
            </div>

            <p className="sched-does">
              {row.mode === 'agent'
                ? row.prompt || 'An agent task with no brief'
                : row.message || row.action.replaceAll('_', ' ')}
            </p>

            {row.mode === 'agent' && (
              <p className="sched-how">
                {row.provider || 'auto provider'} · {row.model || 'auto model'} ·{' '}
                {row.tool_names.length ? `${row.tool_names.length} tools` : 'all tools'} ·{' '}
                {row.delivery}
              </p>
            )}

            {/* What happened last time, which is the thing you check after
                writing one and the thing the old row buried at the bottom. */}
            {row.last_error ? (
              <p className="sched-outcome is-bad">{row.last_error}</p>
            ) : row.last_run ? (
              <p className="sched-outcome">
                ran {row.last_run.slice(0, 16).replace('T', ' ')}
                {row.completed_runs > 1 ? ` · ${row.completed_runs} times` : ''}
                {row.last_tokens ? ` · ${row.last_tokens.toLocaleString()} tokens` : ''}
              </p>
            ) : (
              <p className="sched-outcome is-quiet">has not run yet</p>
            )}

            {row.last_output && <pre className="sched-output">{row.last_output}</pre>}

            <div className="sched-actions">
              <button onClick={() => onAct(row.id, 'run')} type="button">
                <Play aria-hidden="true" /> Run now
              </button>
              <button
                onClick={() => onAct(row.id, row.enabled ? 'disable' : 'enable')}
                type="button"
              >
                {row.enabled ? 'Pause' : 'Resume'}
              </button>
              <button className="is-danger" onClick={() => onAct(row.id, 'remove')} type="button">
                <Trash2 aria-hidden="true" /> Remove
              </button>
            </div>
          </article>
        )
      })}
    </div>
  )
}
