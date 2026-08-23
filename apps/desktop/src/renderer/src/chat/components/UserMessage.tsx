import type { ChatMessage } from '../types'
import { formatTime } from '../time'
import { CopyMessageAction } from './MessageAction'

export function UserMessage({ message }: { message: ChatMessage }): React.JSX.Element {
  return (
    <article className="chat-turn chat-user">
      <div className="chat-user-surface">
        <div className="chat-turn-head">
          <span className="chat-role">YOU</span>
          <span className="chat-time">{formatTime(message.at)}</span>
        </div>
        <div className="chat-body">{message.content}</div>
      </div>
      <div className="chat-turn-actions">
        <CopyMessageAction content={message.content} label="Copy message" />
      </div>
    </article>
  )
}
