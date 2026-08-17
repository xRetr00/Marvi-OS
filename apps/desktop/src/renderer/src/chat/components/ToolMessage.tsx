import { useState } from 'react'

import { Markdown } from '../MarkdownView'
import { formatTime } from '../time'
import { metaValue, type ChatMessage } from '../types'

/**
 * A tool result is somebody else's text, so it reads as evidence, not as
 * Marvi. Collapsed by default; expanding reveals the enveloped result.
 */
export function ToolMessage({ message }: { message: ChatMessage }): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const tool = metaValue(message.meta, 'tool') || 'tool'

  return (
    <div className="chat-turn chat-tool">
      <button
        className="chat-tool-head"
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="chat-role">TOOL · {tool.toUpperCase()}</span>
        <span className="chat-time">
          {formatTime(message.at)} {open ? '▾' : '▸'}
        </span>
      </button>
      {open ? (
        <div className="chat-body chat-tool-body">
          <Markdown content={message.content} />
        </div>
      ) : null}
    </div>
  )
}
