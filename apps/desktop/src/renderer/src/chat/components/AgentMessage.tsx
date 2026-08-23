import { useState } from 'react'

import { Markdown } from '../MarkdownView'
import { formatTime } from '../time'
import { metaValue, type ChatMessage } from '../types'
import { CopyMessageAction } from './MessageAction'

export function AgentMessage({ message }: { message: ChatMessage }): React.JSX.Element {
  const provider = metaValue(message.meta, 'provider')
  const tokens = metaValue(message.meta, 'tokens')
  const reasoning = metaValue(message.meta, 'reasoning')
  const streaming = Boolean(message.meta?.streaming)
  const [showReasoning, setShowReasoning] = useState(false)

  return (
    <article className="chat-turn chat-assistant">
      <div className="chat-turn-head">
        <span className="chat-role">MARVI</span>
        <span className="chat-time">{formatTime(message.at)}</span>
      </div>
      {reasoning ? (
        <div className="chat-reasoning">
          {/* Collapsed by default and never part of the answer. It is the
              model's working, not something Marvi said — and on a thinking
              model it is most of the bill, which is worth being able to see. */}
          <button
            className="chat-reasoning-toggle"
            onClick={() => setShowReasoning((open) => !open)}
            type="button"
          >
            {showReasoning ? '▾' : '▸'} Thinking
          </button>
          {showReasoning ? <pre className="chat-reasoning-body">{reasoning}</pre> : null}
        </div>
      ) : null}
      <div className="chat-body">
        <Markdown content={message.content} />
        {streaming ? (
          // Only while tokens are still arriving. A cursor on a finished
          // message says the reply is unfinished when it is not.
          <span aria-hidden="true" className="chat-cursor" />
        ) : null}
      </div>
      <div className="chat-turn-foot">
        <span className="chat-meta">
          {provider}
          {provider && tokens ? ' · ' : ''}
          {tokens ? `${tokens} tok` : ''}
        </span>
        <div className="chat-turn-actions">
          <CopyMessageAction content={message.content} label="Copy response" />
        </div>
      </div>
    </article>
  )
}
