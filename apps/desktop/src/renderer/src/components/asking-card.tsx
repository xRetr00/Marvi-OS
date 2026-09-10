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
import { useState } from 'react'
import type { Question, Settled } from '../../../shared/asking'
import { readyToSend } from './asking'
import './asking-card.css'

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
