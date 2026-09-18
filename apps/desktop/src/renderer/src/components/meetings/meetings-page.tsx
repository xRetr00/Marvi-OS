/**
 * Meetings: what was said, what was decided, what is now owed.
 *
 * The page is arranged around the one thing it must never get wrong -- who
 * started the recording. There is one button that opens a microphone, it is
 * on this page, and the first time anybody presses it they read a notice
 * about recording other people and accept it once. Marvi can offer; the offer
 * is a card with the same button on it.
 *
 * Everything else is reading: the list, and one meeting's summary, decisions,
 * action items and transcript. A meeting that is still being transcribed says
 * so rather than showing an empty summary, because an empty summary reads like
 * a meeting where nothing was said.
 */
import { useCallback, useEffect, useState } from 'react'
import { Disc, Ear, EarOff, Square, Trash2 } from 'lucide-react'

import type { MeetingCard, MeetingsPage as MeetingsPayload } from '../../../../shared/runtime'

/** What each state means to somebody waiting for their notes. */
const STATES: Record<string, string> = {
  recording: 'recording now',
  transcribing: 'working it up — this takes a few minutes',
  ready: '',
  failed: 'something went wrong'
}

export function MeetingsPage(): React.JSX.Element {
  const [page, setPage] = useState<MeetingsPayload | null>(null)
  const [open, setOpen] = useState<MeetingCard | null>(null)
  const [title, setTitle] = useState('')
  const [notice, setNotice] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setPage((await window.marvi?.getMeetings()) ?? null)
  }, [])

  useEffect(() => {
    void load()
    // While something is recording or being transcribed the page is watching a
    // clock; the rest of the time it is a list and does not need to move.
    const timer = window.setInterval(() => void load(), 5_000)
    return () => window.clearInterval(timer)
  }, [load])

  const start = async (named?: string): Promise<void> => {
    setError('')
    if (!page?.consent.accepted) {
      setNotice(true)
      return
    }
    const began = await window.marvi?.startMeeting((named ?? title).trim())
    if (!began) setError('Marvi could not start recording. Check the microphone and speakers.')
    setTitle('')
    void load()
  }

  const stop = async (id: string): Promise<void> => {
    await window.marvi?.stopMeeting(id)
    void load()
  }

  const read = async (id: string): Promise<void> => {
    const found = await window.marvi?.getMeeting(id)
    if (found) setOpen(found)
  }

  const forget = async (id: string): Promise<void> => {
    await window.marvi?.forgetMeeting(id)
    setOpen(null)
    void load()
  }

  const live = page?.now?.recording ? page.now : null
  const meetings = page?.meetings ?? []

  return (
    <div className="wf-page">
      <header className="cron-head">
        <div>
          <h2>Meetings</h2>
          <p>
            Marvi records your microphone and what your speakers are playing, transcribes both here,
            and tells you what was decided. You start every recording; she never does.
          </p>
        </div>
      </header>

      {page && !page.can_record ? (
        <p className="cron-warn">{page.why_not || 'This machine cannot record a meeting.'}</p>
      ) : null}
      {error ? <p className="cron-warn">{error}</p> : null}

      {/* The offer. It carries the same control as everything else here --
          Marvi asks, and the person still presses the button. */}
      {!live && page?.offer ? (
        <div className="mt-offer">
          <div>
            <strong>{page.offer.title}</strong>
            <span>starts about now. Take notes?</span>
          </div>
          <button
            className="cron-new"
            disabled={!page.can_record}
            onClick={() => void start(page.offer?.title)}
            type="button"
          >
            <Disc aria-hidden="true" />
            Record it
          </button>
        </div>
      ) : null}

      <section className="mt-start">
        {live ? (
          <div className="mt-live">
            <Disc aria-hidden="true" className="mt-live-dot" />
            <div>
              <strong>Recording</strong>
              <span>
                {Math.floor(live.seconds / 60)}:
                {String(Math.floor(live.seconds % 60)).padStart(2, '0')}
                {' · '}
                {live.hearing_you ? (
                  <Ear aria-hidden="true" size={11} />
                ) : (
                  <EarOff aria-hidden="true" size={11} />
                )}
                {live.hearing_you ? ' hearing you' : ' not hearing you'}
                {' · '}
                {live.hearing_them ? ' hearing them' : ' not hearing them'}
              </span>
            </div>
            <button className="cron-new" onClick={() => void stop(live.id)} type="button">
              <Square aria-hidden="true" />
              Stop and write it up
            </button>
          </div>
        ) : (
          <div className="mt-begin">
            <input
              aria-label="What this meeting is"
              onChange={(event) => setTitle(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void start()
              }}
              placeholder="What is this meeting?"
              value={title}
            />
            <button
              className="cron-new"
              disabled={page ? !page.can_record : true}
              onClick={() => void start()}
              type="button"
            >
              <Disc aria-hidden="true" />
              Record
            </button>
          </div>
        )}
      </section>

      <ul className="wf-rule-list">
        {meetings.map((one) => (
          <li key={one.id}>
            <div className="wf-rule-main">
              <div className="wf-rule-words">
                <strong>{one.title}</strong>
                <span className="wf-rule-last">
                  {one.started_at.slice(0, 16).replace('T', ' ')}
                  {one.seconds ? ` · ${Math.round(one.seconds / 60)} min` : ''}
                  {STATES[one.state] ? ` · ${STATES[one.state]}` : ''}
                </span>
                {one.summary ? <span className="wf-rule-when">{one.summary}</span> : null}
              </div>
            </div>
            <div className="wf-rule-acts">
              <button
                disabled={one.state !== 'ready'}
                onClick={() => void read(one.id)}
                type="button"
              >
                Notes
              </button>
              <button
                aria-label={`Forget ${one.title}`}
                onClick={() => void forget(one.id)}
                type="button"
              >
                <Trash2 aria-hidden="true" size={12} />
              </button>
            </div>
          </li>
        ))}
        {meetings.length === 0 ? <li className="wf-empty-row">Nothing recorded yet.</li> : null}
      </ul>

      {notice && page ? (
        <ConsentNotice
          notice={page.consent.notice}
          onAccept={async () => {
            await window.marvi?.acceptMeetingConsent()
            setNotice(false)
            void load()
          }}
          onClose={() => setNotice(false)}
        />
      ) : null}
      {open ? <Notes meeting={open} onClose={() => setOpen(null)} /> : null}
    </div>
  )
}

/** Read once, before Marvi ever records anything. */
function ConsentNotice({
  notice,
  onAccept,
  onClose
}: {
  notice: string
  onAccept: () => void
  onClose: () => void
}): React.JSX.Element {
  return (
    <div className="connector-modal-shell" role="presentation">
      <div
        aria-label="Before recording"
        aria-modal="true"
        className="connector-modal"
        role="dialog"
      >
        <header className="connector-modal-head">
          <div>
            <h3>Before recording</h3>
          </div>
        </header>
        {notice.split('\n\n').map((paragraph) => (
          <p className="wf-body" key={paragraph.slice(0, 24)}>
            {paragraph}
          </p>
        ))}
        <footer className="wf-drawer-foot">
          <button onClick={onClose} type="button">
            Not now
          </button>
          <button onClick={onAccept} type="button">
            I understand
          </button>
        </footer>
      </div>
    </div>
  )
}

/** One meeting: the summary, what was settled, what is owed, and the record. */
function Notes({
  meeting,
  onClose
}: {
  meeting: MeetingCard
  onClose: () => void
}): React.JSX.Element {
  return (
    <div
      className="connector-modal-shell"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      role="presentation"
    >
      <div
        aria-label={meeting.title}
        aria-modal="true"
        className="connector-modal wf-drawer"
        role="dialog"
      >
        <header className="connector-modal-head">
          <div>
            <h3>{meeting.title}</h3>
            <p>
              {meeting.started_at.slice(0, 16).replace('T', ' ')} ·{' '}
              {Math.round((meeting.seconds ?? 0) / 60)} min
            </p>
          </div>
        </header>

        {meeting.summary ? <p className="wf-body">{meeting.summary}</p> : null}

        {meeting.decisions?.length ? (
          <section className="wf-section">
            <h4>Decided</h4>
            <ul className="wf-comments">
              {meeting.decisions.map((one) => (
                <li key={one}>{one}</li>
              ))}
            </ul>
          </section>
        ) : null}

        {meeting.actions?.length ? (
          <section className="wf-section">
            <h4>Owed</h4>
            <ul className="wf-comments">
              {meeting.actions.map((one) => (
                <li key={one}>{one}</li>
              ))}
            </ul>
            <p className="wf-note">Each of these is already a card on the jobs board.</p>
          </section>
        ) : null}

        <section className="wf-section">
          <h4>What was said</h4>
          <ul className="mt-turns">
            {(meeting.turns ?? []).map((turn, index) => (
              <li key={`${turn.at_seconds}-${index}`}>
                <span className="mt-at">
                  {String(Math.floor(turn.at_seconds / 60)).padStart(2, '0')}:
                  {String(turn.at_seconds % 60).padStart(2, '0')}
                </span>
                <span className={turn.speaker === 'you' ? 'wf-who is-you' : 'wf-who'}>
                  {turn.speaker === 'you' ? 'You' : 'Them'}
                </span>
                <span className="mt-said">{turn.text}</span>
              </li>
            ))}
            {meeting.turns?.length === 0 ? (
              <li className="wf-empty">Nothing was heard on either side.</li>
            ) : null}
          </ul>
        </section>
      </div>
    </div>
  )
}
