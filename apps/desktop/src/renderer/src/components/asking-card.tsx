/**
 * The box Marvi puts on screen when hearing the answer wrong would cost more
 * than the question saved — a spelling, an address, an account name.
 *
 * The three buttons are the three real outcomes, and they are separated on
 * purpose. Closing a box is not answering it, and "don't ask me this" is not
 * the same as closing it either: the first earns one spoken follow-up, the
 * second is permanent. A single ✕ would have collapsed all three into the one
 * the user is most likely to hit by accident.
 *
 * There is deliberately no way to submit an empty answer. An empty box that
 * reports itself as answered is the worst of the outcomes — Marvi would file
 * nothing and never ask again.
 */
import { useEffect, useState } from 'react'
import type { Question, Settled } from '../../../shared/asking'
import './asking-card.css'

/** How often to ask the Gateway whether there is a question waiting.
 *
 * Slow, and slower still when the window is hidden. The computer island polled
 * every 250ms for the life of the window and put 1,485 refused requests in the
 * log in under seven minutes; a question box has no reason to be quicker than
 * a person can read. */
const NORMAL = 4_000
const HIDDEN = 30_000

export function useAsking(): Question | null {
  const [waiting, setWaiting] = useState<Question | null>(null)
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    let cooling = NORMAL
    const refresh = async (): Promise<void> => {
      let next = NORMAL
      try {
        const answer = await window.marvi?.getAsking?.()
        if (!answer) throw new Error('Gateway unavailable')
        // One at a time. Two boxes for two questions is a form, and a form is
        // the thing this exists instead of.
        if (alive) setWaiting(answer.waiting?.[0] ?? null)
        cooling = NORMAL
      } catch {
        if (alive) setWaiting(null)
        cooling = Math.min(cooling * 2, HIDDEN)
        next = cooling
      } finally {
        if (alive)
          timer = setTimeout(
            () => void refresh(),
            typeof document !== 'undefined' && document.hidden ? HIDDEN : next
          )
      }
    }
    void refresh()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [])
  return waiting
}

/** What will actually be sent, or empty when there is nothing to send.
 *
 * Pulled out of the component because it is the only decision here worth
 * testing on its own, and the desktop suite renders to static markup -- there
 * is no DOM to type into.
 *
 * Whitespace is not an answer. A box holding three spaces that reports itself
 * answered is the worst of the outcomes: Marvi files nothing, marks the
 * question settled, and never asks again.
 */
export function readyToSend(answer: string): string {
  return answer.trim()
}

export function AskingCard({
  question,
  onSettled
}: {
  question: Question
  onSettled?: (state: Settled) => void
}): React.JSX.Element {
  const [answer, setAnswer] = useState('')
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState('')

  // A new question gets an empty box because the caller mounts this with
  // `key={question.id}`, not because an effect clears it. Resetting state from
  // an effect re-renders once with the previous answer still showing, and the
  // poll runs every four seconds -- so an equal-but-new object would flicker
  // what somebody is halfway through typing.

  const settle = async (state: Settled, said = ''): Promise<void> => {
    setBusy(true)
    setFailed('')
    try {
      await window.marvi.settleAsking(question.id, state, said)
      onSettled?.(state)
    } catch {
      // Left on screen rather than cleared. Clearing it would look like it
      // went through, and Marvi would be waiting for an answer that never
      // arrived.
      setFailed('That did not send. Try again, or tell Marvi out loud.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      aria-label="A question from Marvi"
      className="asking-card"
      onSubmit={(event) => {
        event.preventDefault()
        const said = readyToSend(answer)
        if (said) void settle('answered', said)
      }}
    >
      <p className="asking-question">{question.question}</p>
      <input
        aria-label={question.question}
        autoComplete="off"
        className="asking-input"
        disabled={busy}
        onChange={(event) => setAnswer(event.target.value)}
        onKeyDown={(event) => {
          // Escape closes it, which is not an answer, and Marvi will ask once
          // out loud. That is the intended escape hatch, not a silent no.
          if (event.key === 'Escape' && !busy) void settle('dismissed')
        }}
        // The card only appears because Marvi just asked, so the cursor
        // belongs in the box -- there is nothing else on it to reach.
        autoFocus
        placeholder={question.placeholder || 'Type your answer'}
        type="text"
        value={answer}
      />
      {failed ? (
        <p className="asking-failed" role="alert">
          {failed}
        </p>
      ) : null}
      <div className="asking-actions">
        <button className="asking-send" disabled={busy || !readyToSend(answer)} type="submit">
          Send
        </button>
        <button
          className="asking-later"
          disabled={busy}
          onClick={() => void settle('dismissed')}
          type="button"
        >
          Not now
        </button>
        <button
          className="asking-never"
          disabled={busy}
          onClick={() => void settle('declined')}
          title="Marvi will not ask about this again"
          type="button"
        >
          Don&apos;t ask
        </button>
      </div>
    </form>
  )
}
