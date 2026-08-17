import type { ChatMessage } from '../types'
import { formatTime } from '../time'

export function UserMessage({ message }: { message: ChatMessage }): React.JSX.Element {
  return (
    <div className="chat-turn chat-user">
      <div className="chat-turn-head">
        <span className="chat-role">YOU</span>
        <span className="chat-time">{formatTime(message.at)}</span>
      </div>
      <div className="chat-body">{message.content}</div>
    </div>
  )
}
