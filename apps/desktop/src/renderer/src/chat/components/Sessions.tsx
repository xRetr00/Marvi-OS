import { useState } from 'react'

import type { ChatThread } from '../../../../shared/runtime'
import { AbstractIcon } from '../../components/abstract-icon'
import { TooltipProvider, UiTooltip } from '../../components/ui/tooltip'
import { formatRelative } from '../time'

export function Sessions({
  sessions,
  activeId,
  onSelect,
  onNew,
  onRename,
  onArchive,
  onDelete
}: {
  sessions: ChatThread[]
  activeId: string
  onSelect: (id: string) => void
  onNew: () => void
  onRename: (id: string, title: string) => void
  onArchive: (id: string) => void
  onDelete: (id: string) => void
}): React.JSX.Element {
  const [editing, setEditing] = useState<string | null>(null)
  const [title, setTitle] = useState('')

  return (
    <TooltipProvider>
      <aside className="chat-sessions" aria-label="Chat sessions">
        <div className="chat-sessions-head">
          <span>THREAD INDEX</span>
          <button className="chat-new" type="button" onClick={onNew}>
            <AbstractIcon name="plus" size={13} /> NEW
          </button>
        </div>
        {sessions.length === 0 ? (
          <span className="chat-sessions-empty">NO ACTIVE THREADS</span>
        ) : (
          <ul className="chat-session-list">
            {sessions.map((session, index) => (
              <li key={session.id} className={session.id === activeId ? 'active' : ''}>
                {editing === session.id ? (
                  <form
                    className="chat-session-rename"
                    onSubmit={(event) => {
                      event.preventDefault()
                      if (title.trim()) onRename(session.id, title)
                      setEditing(null)
                    }}
                  >
                    <input
                      aria-label="Thread title"
                      autoFocus
                      value={title}
                      onBlur={() => setEditing(null)}
                      onChange={(event) => setTitle(event.target.value)}
                    />
                  </form>
                ) : (
                  <button
                    className="chat-session"
                    type="button"
                    onClick={() => onSelect(session.id)}
                  >
                    <span className="chat-session-index">{String(index + 1).padStart(2, '0')}</span>
                    <span className="chat-session-copy">
                      <span className="chat-session-title">{session.title}</span>
                      <span className="chat-session-meta">
                        {session.message_count} msgs · {formatRelative(session.updated_at)}
                      </span>
                    </span>
                  </button>
                )}
                <div className="chat-session-actions">
                  <UiTooltip label="Rename thread">
                    <button
                      aria-label="Rename thread"
                      type="button"
                      onClick={() => {
                        setTitle(session.title)
                        setEditing(session.id)
                      }}
                    >
                      <AbstractIcon name="edit" size={13} />
                    </button>
                  </UiTooltip>
                  <UiTooltip label="Archive thread">
                    <button
                      aria-label="Archive thread"
                      type="button"
                      onClick={() => onArchive(session.id)}
                    >
                      <AbstractIcon name="archive" size={13} />
                    </button>
                  </UiTooltip>
                  <UiTooltip label="Delete thread">
                    <button
                      aria-label="Delete thread"
                      type="button"
                      onClick={() => onDelete(session.id)}
                    >
                      <AbstractIcon name="close" size={13} />
                    </button>
                  </UiTooltip>
                </div>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </TooltipProvider>
  )
}
