import { useState } from 'react'
import { ChevronDown } from 'lucide-react'

import { haptic } from '../../lib/haptics'
import { Markdown } from '../MarkdownView'
import { ActivityTimer } from './ActivityTimer'

export function ReasoningDisclosure({
  reasoning,
  startedAt,
  streaming
}: {
  reasoning: string
  startedAt: string
  streaming: boolean
}): React.JSX.Element {
  const [userOpen, setUserOpen] = useState<boolean | null>(null)
  const open = userOpen ?? streaming

  return (
    <section
      className="chat-scaffold chat-reasoning"
      data-conversation-scaffold=""
      data-state={streaming ? 'streaming' : 'complete'}
    >
      <button
        aria-expanded={open}
        className="chat-disclosure-row"
        onClick={() => {
          haptic('selection')
          setUserOpen(!open)
        }}
        type="button"
      >
        {streaming ? <span aria-hidden="true" className="chat-activity-pulse" /> : null}
        <span className={streaming ? 'chat-scaffold-label is-live' : 'chat-scaffold-label'}>
          {streaming ? 'Thinking' : 'Thought'}
        </span>
        {streaming ? <ActivityTimer active startedAt={startedAt} /> : null}
        <ChevronDown
          aria-hidden="true"
          className={open ? 'chat-disclosure-caret is-open' : 'chat-disclosure-caret'}
          size={13}
          strokeWidth={1.6}
        />
      </button>
      {open ? (
        <div className={streaming ? 'chat-reasoning-body is-live' : 'chat-reasoning-body'}>
          <Markdown content={reasoning} />
        </div>
      ) : null}
    </section>
  )
}

export function StreamActivity({
  label = 'Working',
  startedAt
}: {
  label?: string
  startedAt: string
}): React.JSX.Element {
  return (
    <div className="chat-scaffold chat-stream-activity" data-conversation-scaffold="" role="status">
      <span aria-hidden="true" className="chat-activity-pulse" />
      <span className="chat-scaffold-label is-live">{label}</span>
      <ActivityTimer active startedAt={startedAt} />
    </div>
  )
}
