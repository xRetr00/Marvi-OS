import { useEffect, useState } from 'react'

import type { ChatAttachment } from '../../../../shared/runtime'
import { AbstractIcon } from '../../components/abstract-icon'
import { formatBytes } from '../attachment-format'

export function PendingAttachment({
  attachment,
  onRemove
}: {
  attachment: ChatAttachment
  onRemove: () => void
}): React.JSX.Element {
  const [source, setSource] = useState('')

  useEffect(() => {
    if (attachment.kind !== 'image') return
    let disposed = false
    void window.marvi?.getChatAttachment(attachment.id).then((value) => {
      if (!disposed && value) setSource(`data:${value.mediaType};base64,${value.data}`)
    })
    return () => {
      disposed = true
    }
  }, [attachment.id, attachment.kind])

  return (
    <span className="chat-attachment">
      <span className="chat-attachment-thumb">
        {source ? (
          <img alt="" src={source} />
        ) : (
          <AbstractIcon name={attachment.kind === 'image' ? 'vision' : 'paperclip'} size={14} />
        )}
      </span>
      <span className="chat-attachment-copy">
        <strong>{attachment.name}</strong>
        <small>
          {attachment.kind === 'image' ? 'IMAGE' : fileExtension(attachment.name)} ·{' '}
          {formatBytes(attachment.size)}
        </small>
      </span>
      <button aria-label={`Remove ${attachment.name}`} onClick={onRemove} type="button">
        <AbstractIcon name="close" size={11} />
      </button>
    </span>
  )
}

function fileExtension(name: string): string {
  const extension = name.split('.').pop()?.trim()
  return extension && extension !== name ? extension.toUpperCase() : 'FILE'
}
