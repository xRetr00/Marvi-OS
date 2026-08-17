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
      <div className="chat-body">
        <Markdown content={message.content} />
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
