import { useState } from 'react'

import { Markdown } from '../MarkdownView'
import { formatTime } from '../time'
import { metaValue, type ChatMessage } from '../types'

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

export function AgentMessage({ message }: { message: ChatMessage }): React.JSX.Element {
  const [copied, setCopied] = useState(false)
  const provider = metaValue(message.meta, 'provider')
  const tokens = metaValue(message.meta, 'tokens')
  const reasoning = metaValue(message.meta, 'reasoning')
  const streaming = Boolean(message.meta?.streaming)
  const [showReasoning, setShowReasoning] = useState(false)

  const copy = async (): Promise<void> => {
    if (await copyText(message.content)) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }
  }

  return (
    <div className="chat-turn chat-assistant">
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
        <button className="chat-copy" type="button" onClick={() => void copy()}>
          {copied ? 'COPIED' : 'COPY'}
        </button>
      </div>
    </div>
  )
}
