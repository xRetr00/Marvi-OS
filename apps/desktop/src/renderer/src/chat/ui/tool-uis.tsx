/**
 * Generative UI: the components assistant-ui draws for a tool call.
 *
 * Two of them do real work. `marvi_widget` draws the Gateway's validated widget
 * vocabulary -- the same nine renderers as before, reached through the SDK
 * rather than through a filter over message parts. `marvi_ask` draws the
 * question a chat turn is currently blocked on, and answering it calls
 * `addResult`, which is what lets the turn carry on instead of ending and
 * being restarted by the user's next message.
 *
 * Everything else falls to `ToolActivity`, a one-line "used X" -- a tool with
 * no UI of its own should read as a footnote, not as a card.
 *
 * ## A widget can never name its own renderer
 *
 * `WidgetStack` picks a component from a fixed table keyed by `kind`, and
 * `kind` is one of nine strings the Gateway validated. Widget data is drawn as
 * data and never evaluated, so a tool result cannot reach the renderer.
 */

import { useState } from 'react'
import type { ToolCallMessagePartProps } from '@assistant-ui/react'

import type { ChatWidgetPart } from '../../../../shared/runtime'
import { AbstractIcon } from '../../components/abstract-icon'
import { GlyphSpinner } from '../../components/ui/glyph-spinner'
import { WidgetStack } from '../components/WidgetStack'
import { ActivityLabel } from './ActivityLabel'

/** `present_widget` and every tool the Gateway derived a widget from. */
export function WidgetToolUI({
  result,
  status
}: ToolCallMessagePartProps): React.JSX.Element | null {
  if (status.type === 'running' || result == null) {
    return (
      <div className="chat-scaffold chat-inline-tool" data-conversation-scaffold="">
        <GlyphSpinner
          ariaLabel="Marvi is preparing a widget"
          className="chat-working-spinner"
          spinner="braille"
        />
        <ActivityLabel live text="Marvi is preparing a widget" />
      </div>
    )
  }
  const widget = result as ChatWidgetPart
  if (!widget || widget.type !== 'widget') return null
  return <WidgetStack parts={[widget]} />
}

/** A tool with no UI of its own. One line, past tense, no card. */
export function ToolActivity({ toolName, status }: ToolCallMessagePartProps): React.JSX.Element {
  const running = status.type === 'running'
  return (
    <div className="chat-scaffold chat-inline-tool" data-conversation-scaffold="">
      {running ? (
        <GlyphSpinner
          ariaLabel={`Marvi is using ${toolLabel(toolName)}`}
          className="chat-working-spinner"
          spinner="braille"
        />
      ) : (
        <span aria-hidden="true" className="chat-tool-dot" />
      )}
      <ActivityLabel
        live={running}
        text={`${running ? 'Marvi is using' : 'Marvi used'} ${toolLabel(toolName)}`}
      />
    </div>
  )
}

type AskArgs = {
  kind?: 'clarify' | 'secret'
  question?: string
  choices?: string[]
  multi_select?: boolean
  name?: string
  why?: string
}

/**
 * `clarify` and `ask_secret`, in the transcript, with the turn waiting.
 *
 * `addResult` is the whole point: it hands the answer back as the tool's
 * result, so the model receives it as a result rather than as a new user
 * message and never has to be told to stop and wait.
 */
export function AskToolUI({
  args,
  result,
  addResult,
  status
}: ToolCallMessagePartProps): React.JSX.Element {
  const ask = (args ?? {}) as AskArgs
  const settled = result != null || status.type === 'complete'
  if (ask.kind === 'secret') {
    return <SecretCard ask={ask} settled={settled} onSettled={(a) => addResult({ answer: a })} />
  }
  return <ClarifyCard ask={ask} settled={settled} onAnswer={(a) => addResult({ answer: a })} />
}

function ClarifyCard({
  ask,
  settled,
  onAnswer
}: {
  ask: AskArgs
  settled: boolean
  onAnswer: (answer: string) => void
}): React.JSX.Element {
  const [typed, setTyped] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const multi = Boolean(ask.multi_select)
  const choices = ask.choices ?? []

  if (settled) {
    return (
      <div className="chat-ask chat-ask-settled" data-conversation-scaffold="">
        <AbstractIcon name="check" size={13} />
        <span className="chat-scaffold-label">Answered</span>
      </div>
    )
  }

  const send = (answer: string): void => {
    const clean = answer.trim()
    if (clean) onAnswer(clean)
  }

  return (
    <form
      aria-label="A question from Marvi"
      className="chat-ask"
      data-conversation-scaffold=""
      onSubmit={(event) => {
        event.preventDefault()
        // Typed text wins over a selection: somebody who typed after picking
        // meant the typing. Nothing here can submit an empty answer -- a
        // question that reports itself answered with nothing in it is the
        // worst outcome, because Marvi files nothing and moves on.
        send(typed || picked.join(', '))
      }}
    >
      <p className="chat-ask-question">{ask.question}</p>
      {choices.length ? (
        <div className="chat-ask-choices" role={multi ? 'group' : 'radiogroup'}>
          {choices.map((choice) => {
            const chosen = picked.includes(choice)
            return (
              <button
                aria-pressed={multi ? chosen : undefined}
                className={chosen ? 'chat-ask-choice is-chosen' : 'chat-ask-choice'}
                key={choice}
                onClick={() => {
                  if (!multi) {
                    // A single-choice answer is one tap. Making it a tap and
                    // then a Send is the extra step the tool exists to avoid.
                    send(choice)
                    return
                  }
                  setPicked((current) =>
                    current.includes(choice)
                      ? current.filter((entry) => entry !== choice)
                      : [...current, choice]
                  )
                }}
                type="button"
              >
                {choice}
              </button>
            )
          })}
        </div>
      ) : null}
      <div className="chat-ask-actions">
        <input
          aria-label={ask.question || 'Your answer'}
          autoComplete="off"
          className="chat-ask-input"
          onChange={(event) => setTyped(event.target.value)}
          placeholder={choices.length ? 'Or type something else' : 'Type your answer'}
          type="text"
          value={typed}
        />
        <button className="chat-ask-send" disabled={!typed.trim() && !picked.length} type="submit">
          SEND
        </button>
      </div>
    </form>
  )
}

/**
 * A masked field. The value goes desktop -> Gateway -> settings store and is
 * never put into the transcript, the turn, or the model's context -- the tool
 * result is the word "saved".
 */
function SecretCard({
  ask,
  settled,
  onSettled
}: {
  ask: AskArgs
  settled: boolean
  onSettled: (answer: string) => void
}): React.JSX.Element {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState('')
  const setting = ask.name || 'SETTING'

  if (settled) {
    return (
      <div className="chat-ask chat-ask-settled" data-conversation-scaffold="">
        <AbstractIcon name="check" size={13} />
        <span className="chat-scaffold-label">{setting} saved</span>
      </div>
    )
  }

  const save = async (): Promise<void> => {
    setBusy(true)
    setFailed('')
    try {
      const stored = await window.marvi?.saveSecret({ id: '', name: setting, value })
      if (!stored) throw new Error('not stored')
      // Cleared before the turn is told, so the value does not sit in a React
      // state tree waiting for a re-render.
      setValue('')
      onSettled('saved')
    } catch {
      setFailed('That did not save. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      aria-label={`Marvi needs ${setting}`}
      className="chat-ask chat-ask-secret"
      data-conversation-scaffold=""
      onSubmit={(event) => {
        event.preventDefault()
        if (value) void save()
      }}
    >
      <p className="chat-ask-question">
        <code>{setting}</code>
      </p>
      {ask.why ? <p className="chat-ask-why">{ask.why}</p> : null}
      <div className="chat-ask-actions">
        <input
          aria-label={setting}
          autoComplete="off"
          className="chat-ask-input"
          disabled={busy}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Paste it here"
          // Masked, never logged, never echoed. The one field in Chat that is.
          type="password"
          value={value}
        />
        <button className="chat-ask-send" disabled={busy || !value} type="submit">
          SAVE
        </button>
        <button
          className="chat-ask-skip"
          disabled={busy}
          onClick={() => onSettled('skipped')}
          type="button"
        >
          NOT NOW
        </button>
      </div>
      {failed ? (
        <p className="chat-ask-failed" role="alert">
          {failed}
        </p>
      ) : null}
    </form>
  )
}

function toolLabel(tool: string): string {
  return tool.replaceAll(/[_-]+/g, ' ').replace(/^\w/, (letter) => letter.toUpperCase())
}
