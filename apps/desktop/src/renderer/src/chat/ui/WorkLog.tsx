/**
 * "Marvi worked for 12s" -- the disclosure that holds everything she did on the
 * way to an answer: thoughts, commentary, and each tool call with what it was
 * asked and what it returned.
 *
 * Open while she works, so you can watch it happen; collapsed once she is done,
 * so a finished reply leads with its answer. After that it keeps whatever you
 * last chose. That is the same rule the thinking disclosure follows, for the
 * same reason: a panel that snaps shut on the next render punishes you for
 * opening it.
 */

import { useEffect, useState } from 'react'
import { ChevronDown } from 'lucide-react'

import { GlyphSpinner } from '../../components/ui/glyph-spinner'
import { Markdown } from '../MarkdownView'
import { ActivityLabel } from './ActivityLabel'
import { formatWorked } from './group-work'
import { toolSentence } from './tool-verbs'

export function WorkLog({
  running,
  activity,
  startedAt,
  workedMs,
  steps,
  children
}: {
  running: boolean
  /** What she is doing right now, for the header while it runs. */
  activity: string
  startedAt: number
  /** Stored duration, once the turn has finished. */
  workedMs: number
  /** How many tool calls the run made, for the collapsed summary. */
  steps: number
  children: React.ReactNode
}): React.JSX.Element {
  const [chosen, setChosen] = useState<boolean | null>(null)
  const open = chosen ?? running
  const elapsed = useElapsed(running, startedAt)
  const duration = running ? elapsed : workedMs

  const summary = running
    ? activity
    : duration > 0
      ? `Marvi worked for ${formatWorked(duration)}`
      : 'Marvi worked on this'

  return (
    <section
      className="chat-work"
      data-conversation-scaffold=""
      data-state={running ? 'running' : 'complete'}
    >
      <button
        aria-expanded={open}
        className="chat-work-head"
        onClick={() => setChosen(!open)}
        type="button"
      >
        {running ? (
          <GlyphSpinner ariaLabel={activity} className="chat-working-spinner" />
        ) : (
          <span aria-hidden="true" className="chat-work-dot" />
        )}
        <ActivityLabel live={running} text={summary} />
        {running && duration > 0 ? (
          <span className="chat-work-time">{formatWorked(duration)}</span>
        ) : null}
        {!running && steps > 0 ? (
          <span className="chat-work-count">
            {steps} {steps === 1 ? 'step' : 'steps'}
          </span>
        ) : null}
        <ChevronDown
          aria-hidden="true"
          className={open ? 'chat-disclosure-caret is-open' : 'chat-disclosure-caret'}
          size={13}
          strokeWidth={1.6}
        />
      </button>
      {open ? <ol className="chat-work-steps">{children}</ol> : null}
    </section>
  )
}

/** Seconds since `startedAt`, ticking while `active`. */
function useElapsed(active: boolean, startedAt: number): number {
  const [now, setNow] = useState(startedAt)
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setNow(Date.now()), 1_000)
    return () => window.clearInterval(timer)
  }, [active])
  return Math.max(0, now - startedAt)
}

export function ThoughtStep({ text, live }: { text: string; live: boolean }): React.JSX.Element {
  return (
    <li className={live ? 'chat-work-step is-thought is-live' : 'chat-work-step is-thought'}>
      <div className="chat-work-thought">
        <Markdown content={text} />
      </div>
    </li>
  )
}

export function CommentaryStep({ text }: { text: string }): React.JSX.Element {
  return (
    <li className="chat-work-step is-commentary">
      <div className="chat-work-commentary">
        <Markdown content={text} />
      </div>
    </li>
  )
}

/**
 * One call: the sentence for what it did, and -- on request -- exactly what it
 * was asked and what came back. Collapsed by default: the sentence is what you
 * skim, the arguments are what you check when the answer looks wrong.
 */
export function ToolStep({
  name,
  args,
  result,
  status
}: {
  name: string
  args: Record<string, unknown>
  result: string
  status: 'running' | 'complete' | 'failed'
}): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const running = status === 'running'
  const argText = Object.keys(args).length ? JSON.stringify(args, null, 2) : ''
  const hasDetail = Boolean(argText || result)

  return (
    <li className={`chat-work-step is-tool is-${status}`}>
      <button
        aria-expanded={hasDetail ? open : undefined}
        className="chat-work-tool"
        disabled={!hasDetail}
        onClick={() => setOpen(!open)}
        type="button"
      >
        {running ? (
          <GlyphSpinner ariaLabel={toolSentence(name, true)} className="chat-working-spinner" />
        ) : (
          <span aria-hidden="true" className="chat-work-tool-dot" />
        )}
        <ActivityLabel live={running} text={toolSentence(name, running)} />
        {status === 'failed' ? <span className="chat-work-failed">failed</span> : null}
        {hasDetail ? (
          <ChevronDown
            aria-hidden="true"
            className={open ? 'chat-disclosure-caret is-open' : 'chat-disclosure-caret'}
            size={12}
            strokeWidth={1.6}
          />
        ) : null}
      </button>
      {open && hasDetail ? (
        <div className="chat-work-detail">
          {argText ? (
            <>
              <span className="chat-work-detail-label">Asked</span>
              <pre>{argText}</pre>
            </>
          ) : null}
          {result ? (
            <>
              <span className="chat-work-detail-label">Returned</span>
              <pre>{result}</pre>
            </>
          ) : null}
        </div>
      ) : null}
    </li>
  )
}
