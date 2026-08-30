import { formatTime } from '../time'
import type { ChatMessage } from '../types'
import { AbstractIcon } from '../../components/abstract-icon'
import { CopyMessageAction } from './MessageAction'

export function ErrorMessage({ message }: { message: ChatMessage }): React.JSX.Element {
  return (
    <article className="chat-turn chat-error" role="alert">
      <div className="chat-error-surface">
        <AbstractIcon className="chat-error-icon" name="about" size={15} />
        <div>
          <strong>Response failed</strong>
          <div className="chat-body">{message.content}</div>
        </div>
      </div>
      <div className="chat-turn-actions">
        <span className="chat-message-age">{formatTime(message.at)}</span>
        <CopyMessageAction content={message.content} label="Copy error details" />
      </div>
    </article>
  )
}
