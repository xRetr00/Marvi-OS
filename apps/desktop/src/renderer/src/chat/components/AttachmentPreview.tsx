import { useEffect, useState } from 'react'

import type { ChatAttachment } from '../../../../shared/runtime'
import { AbstractIcon } from '../../components/abstract-icon'

export function AttachmentPreview({
  attachment
}: {
  attachment: ChatAttachment
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

  if (attachment.kind === 'image') {
    return (
      <figure className="chat-image-attachment">
        {source ? <img alt={attachment.name} src={source} /> : <span aria-hidden="true" />}
        <figcaption>{attachment.name}</figcaption>
      </figure>
    )
  }

  return (
    <span className="chat-document-attachment">
      <AbstractIcon name="paperclip" size={12} />
      {attachment.name}
      <small>{formatBytes(attachment.size)}</small>
    </span>
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
