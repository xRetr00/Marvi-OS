/**
 * The board: every job Marvi is doing, has done, or is stuck on.
 *
 * One column per state, because the question a person opens this with is
 * "what is stuck" and a single list answers it last. The columns that matter
 * are the middle ones -- `awaiting_approval` and `blocked` are the two that
 * want something *from you*, so they sit where the eye lands and carry the
 * only colour on the page.
 *
 * It does not poll on a timer. `GET /jobs?after=<revision>` holds open until
 * something changes, which is both cheaper and steadier to read: a board that
 * repaints every two seconds is one nobody can follow while it changes.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { CircleDot, Clock3, Hand, Pause, ShieldQuestion, X } from 'lucide-react'

import type { JobBoard, JobCard } from '../../../../shared/runtime'

/** The columns, in the order a job travels through them. */
const COLUMNS: { id: string; label: string; icon: typeof Clock3; wants?: boolean }[] = [
  { id: 'todo', label: 'To do', icon: Clock3 },
  { id: 'running', label: 'Running', icon: CircleDot },
  { id: 'awaiting_approval', label: 'Needs you', icon: ShieldQuestion, wants: true },
  { id: 'blocked', label: 'Blocked', icon: Hand, wants: true },
  { id: 'done', label: 'Done', icon: Pause },
  { id: 'failed', label: 'Failed', icon: X }
]

/** Why a card is blocked, in words rather than a field name. */
const BLOCKED: Record<string, string> = {
  needs_input: 'waiting on an answer',
  dependency: 'waiting on something else',
  stalled: 'stopped making progress',
  restart: 'the Gateway restarted while it ran'
}

export function JobsBoard(): React.JSX.Element {
  const [board, setBoard] = useState<JobBoard | null>(null)
  const [open, setOpen] = useState<JobCard | null>(null)
  const revision = useRef(-1)

  // The long poll: ask for the board, then ask again for whatever comes after
  // the revision we were given. No timer anywhere in here.
  useEffect(() => {
    let alive = true
    const follow = async (): Promise<void> => {
      while (alive) {
        const next = await window.marvi?.getJobs(revision.current)
        if (!alive) return
        if (next) {
          revision.current = next.revision
          setBoard(next)
        } else {
          // The Gateway is not answering; wait before asking again rather
          // than spinning against a closed socket.
          await new Promise((wake) => setTimeout(wake, 3_000))
        }
      }
    }
    void follow()
    return () => {
      alive = false
    }
  }, [])

  const refresh = useCallback(async (id: string) => {
    const card = await window.marvi?.getJob(id)
    if (card) setOpen(card)
  }, [])

  const waiting =
    (board?.columns?.awaiting_approval?.length ?? 0) + (board?.columns?.blocked?.length ?? 0)

  return (
    <div className="wf-board">
      <header className="wf-head">
        <div>
          <h3>Jobs</h3>
          <p>
            Everything handed to a sub-agent or written down for later. Cards survive a restart; one
            interrupted by a restart says so.
          </p>
        </div>
        {waiting > 0 ? <span className="wf-waiting">{waiting} waiting on you</span> : null}
      </header>

      <div className="wf-columns">
        {COLUMNS.map((column) => {
          const cards = board?.columns?.[column.id] ?? []
          const Icon = column.icon
          return (
            <section
              className={`wf-column${column.wants && cards.length ? ' is-wanted' : ''}`}
              key={column.id}
            >
              <header>
                <Icon aria-hidden="true" size={12} />
                <span>{column.label}</span>
                <span className="wf-count">{cards.length}</span>
              </header>
              <ul>
                {cards.map((card) => (
                  <li key={card.id}>
                    <button onClick={() => void refresh(card.id)} type="button">
                      <span className="wf-card-title">{card.title}</span>
                      <span className="wf-card-meta">
                        <span className="wf-who">{card.assignee}</span>
                        {card.reason ? (
                          <span className="wf-why">{BLOCKED[card.reason] ?? card.reason}</span>
                        ) : null}
                      </span>
                    </button>
                  </li>
                ))}
                {cards.length === 0 ? <li className="wf-empty">—</li> : null}
              </ul>
            </section>
          )
        })}
      </div>

      {open ? <JobDrawer card={open} onClose={() => setOpen(null)} onChanged={refresh} /> : null}
    </div>
  )
}

/** One card, with every attempt, comment and transition it carries. */
function JobDrawer({
  card,
  onClose,
  onChanged
}: {
  card: JobCard
  onClose: () => void
  onChanged: (id: string) => void
}): React.JSX.Element {
  const [comment, setComment] = useState('')
  const [sending, setSending] = useState(false)
  const live = ['todo', 'running', 'awaiting_approval', 'blocked'].includes(card.status)

  const say = async (): Promise<void> => {
    if (!comment.trim()) return
    setSending(true)
    await window.marvi?.commentOnJob(card.id, comment.trim())
    setComment('')
    setSending(false)
    onChanged(card.id)
  }

  return (
    <div
      className="connector-modal-shell"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      role="presentation"
    >
      <div
        aria-label={card.title}
        aria-modal="true"
        className="connector-modal wf-drawer"
        role="dialog"
      >
        <button
          aria-label="Close"
          className="connector-modal-close"
          onClick={onClose}
          type="button"
        >
          <X aria-hidden="true" size={14} />
        </button>
        <header className="connector-modal-head">
          <div>
            <h3>{card.title}</h3>
            <p>
              {card.assignee}
              {card.mode ? ` · ${card.mode}` : ''} · {card.status.replace('_', ' ')}
              {card.reason ? ` · ${BLOCKED[card.reason] ?? card.reason}` : ''}
            </p>
          </div>
        </header>

        {card.body && card.body !== card.title ? <p className="wf-body">{card.body}</p> : null}

        {card.runs?.length ? (
          <section className="wf-section">
            <h4>Attempts</h4>
            <ul className="wf-runs">
              {card.runs.map((run) => (
                <li key={run.id}>
                  <span className="wf-run-when">{run.started_at.slice(11, 16)}</span>
                  <span className="wf-run-reason">{run.exit_reason || 'running'}</span>
                  {run.summary ? <span className="wf-run-summary">{run.summary}</span> : null}
                  {run.tokens ? (
                    <span className="wf-run-tokens">{run.tokens.toLocaleString()}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <section className="wf-section">
          <h4>Comments</h4>
          <ul className="wf-comments">
            {(card.comments ?? []).map((one) => (
              <li key={one.id}>
                <span className="wf-who">{one.author}</span>
                <span>{one.body}</span>
              </li>
            ))}
            {card.comments?.length === 0 ? <li className="wf-empty">Nothing said yet.</li> : null}
          </ul>
          <div className="wf-say">
            <input
              aria-label="Add a comment"
              onChange={(event) => setComment(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void say()
              }}
              placeholder={live ? 'Say something to this job…' : 'Add a note…'}
              value={comment}
            />
            <button disabled={sending || !comment.trim()} onClick={() => void say()} type="button">
              {live ? 'Steer' : 'Note'}
            </button>
          </div>
          {live ? (
            <p className="wf-note">
              A comment on a running job reaches it: the sub-agent is told, mid-work.
            </p>
          ) : null}
        </section>

        <footer className="wf-drawer-foot">
          {live ? (
            <button
              onClick={() =>
                void window.marvi
                  ?.updateJob(card.id, { status: 'cancelled' })
                  .then(() => onChanged(card.id))
              }
              type="button"
            >
              Cancel job
            </button>
          ) : null}
          {card.status !== 'done' ? (
            <button
              onClick={() =>
                void window.marvi
                  ?.updateJob(card.id, { status: 'done' })
                  .then(() => onChanged(card.id))
              }
              type="button"
            >
              Mark done
            </button>
          ) : null}
        </footer>
      </div>
    </div>
  )
}
