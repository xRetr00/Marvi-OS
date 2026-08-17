import { formatTime } from '../time'
import type { ChatMessage } from '../types'

export function ErrorMessage({ message }: { message: ChatMessage }): React.JSX.Element {
  return (
    <div className="chat-turn chat-error">
      <div className="chat-turn-head">
        <span className="chat-role">ERROR</span>
        <span className="chat-time">{formatTime(message.at)}</span>
      </div>
      <div className="chat-body">{message.content}</div>
    </div>
  )
}
