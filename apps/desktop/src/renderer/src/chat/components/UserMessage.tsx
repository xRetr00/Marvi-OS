import { useState } from 'react'

import { AbstractIcon } from '../../components/abstract-icon'
import { UiTooltip } from '../../components/ui/tooltip'
import { formatTime } from '../time'
import type { ChatMessage } from '../types'
import { CopyMessageAction } from './MessageAction'
import { AttachmentPreview } from './AttachmentPreview'

export function UserMessage({
  message,
  onEdit
}: {
  message: ChatMessage
  onEdit?: (id: number, content: string) => void
}): React.JSX.Element {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(message.content)
  return (
    <article
      className="chat-turn chat-user"
      aria-label="Your message"
      data-role="user"
      data-slot="chat-user-message"
    >
      <span className="sr-only">YOU</span>
      <div className="chat-user-surface" data-slot="chat-user-surface">
        {editing ? (
          <form
            className="chat-message-edit"
            onSubmit={(event) => {
              event.preventDefault()
              if (draft.trim()) onEdit?.(message.id, draft)
              setEditing(false)
            }}
          >
            <textarea
              aria-label="Edit message"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
            <div>
              <button type="button" onClick={() => setEditing(false)}>
                CANCEL
              </button>
              <button type="submit">SEND EDIT</button>
            </div>
          </form>
        ) : (
          <div className="chat-body chat-user-text">{message.content}</div>
        )}
        {message.attachments.length ? (
          <div className="chat-message-files">
            {message.attachments.map((attachment) => (
              <AttachmentPreview attachment={attachment} key={attachment.id} />
            ))}
          </div>
        ) : null}
      </div>
      <div className="chat-turn-actions">
        <span className="chat-message-age">{formatTime(message.at)}</span>
        {onEdit && message.id > 0 ? (
          <UiTooltip label="Edit and branch from this message">
            <button aria-label="Edit message" onClick={() => setEditing(true)} type="button">
              <AbstractIcon name="edit" size={14} />
            </button>
          </UiTooltip>
        ) : null}
        <CopyMessageAction content={message.content} label="Copy message" />
      </div>
    </article>
  )
}
