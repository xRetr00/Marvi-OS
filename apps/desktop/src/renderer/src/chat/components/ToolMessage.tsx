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
    <details
      className="chat-turn chat-tool"
      data-conversation-scaffold=""
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary className="chat-tool-head">
        <span className="chat-widget-glyph" aria-hidden="true" />
        <strong>{toolLabel(tool)}</strong>
        <span className="chat-tool-time">{formatTime(message.at)}</span>
        <span className="chat-tool-caret" aria-hidden="true">
          ›
        </span>
      </summary>
      {open ? (
        <div className="chat-tool-result">
          <div className="chat-body chat-tool-body">
            <Markdown content={message.content} />
          </div>
        </div>
      ) : null}
    </details>
  )
}

function toolLabel(tool: string): string {
  return tool.replaceAll(/[_-]+/g, ' ').replace(/^\w/, (letter) => letter.toUpperCase())
}
