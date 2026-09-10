import { useEffect, useState } from 'react'

import type { ChatAttachment } from '../../../../shared/runtime'
import { AbstractIcon } from '../../components/abstract-icon'
import { formatBytes } from '../attachment-format'

/** Only the fields this actually reads.
 *
 * Narrowed so a caller holding an SDK attachment -- which has an id, a name
 * and a mime type and nothing else -- can render one without inventing a
 * thread id and a timestamp to satisfy a type. */
export type PreviewableAttachment = Pick<
  ChatAttachment,
  'id' | 'name' | 'media_type' | 'size' | 'kind'
>

export function AttachmentPreview({
  attachment
}: {
  attachment: PreviewableAttachment
}): React.JSX.Element {
  const [source, setSource] = useState('')
  const [expanded, setExpanded] = useState(false)

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

  useEffect(() => {
    if (!expanded) return
    const close = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setExpanded(false)
    }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [expanded])

  if (attachment.kind === 'image') {
    return (
      <>
        <figure className="chat-image-attachment">
          <button
            aria-label={`Open ${attachment.name}`}
            disabled={!source}
            onClick={() => setExpanded(true)}
            type="button"
          >
            {source ? <img alt={attachment.name} src={source} /> : <span aria-hidden="true" />}
          </button>
          <figcaption>
            <span>{attachment.name}</span>
            <small>{formatBytes(attachment.size)}</small>
          </figcaption>
        </figure>
        {expanded && source ? (
          <div
            aria-label={`${attachment.name} preview`}
            aria-modal="true"
            className="chat-image-lightbox"
            onClick={() => setExpanded(false)}
            role="dialog"
          >
            <button
              aria-label="Close image preview"
              onClick={() => setExpanded(false)}
              type="button"
            >
              <AbstractIcon name="close" size={16} />
            </button>
            <img alt={attachment.name} onClick={(event) => event.stopPropagation()} src={source} />
            <span>{attachment.name}</span>
          </div>
        ) : null}
      </>
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
