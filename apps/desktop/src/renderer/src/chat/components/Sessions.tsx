import { useState } from 'react'
import type { ReactNode } from 'react'
import TelegramLogo from '@thesvg/react/telegram'

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
  onDelete,
  onExit,
  onExport,
  exportDisabled,
  timing
}: {
  sessions: ChatThread[]
  activeId: string
  onSelect: (id: string) => void
  onNew: () => void
  onRename: (id: string, title: string) => void
  onArchive: (id: string) => void
  onDelete: (id: string) => void
  onExit: () => void
  onExport: () => void
  exportDisabled: boolean
  timing: ReactNode
}): React.JSX.Element {
  const [editing, setEditing] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [query, setQuery] = useState('')
  const visibleSessions = sessions.filter((session) =>
    session.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
  )
  // Phone conversations get their own group: they are the same Marvi, but a
  // different place, and mixing them into Recent hides which is which.
  const recent = visibleSessions.filter((session) => session.channel !== 'telegram')
  const telegram = visibleSessions.filter((session) => session.channel === 'telegram')

  const list = (items: ChatThread[]): React.JSX.Element => (
    <ul className="chat-session-list">
      {items.map((session) => (
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
            <button className="chat-session" type="button" onClick={() => onSelect(session.id)}>
              {session.channel === 'telegram' ? (
                <TelegramLogo aria-hidden="true" className="chat-session-logo" />
              ) : (
                <span className="chat-session-dot" aria-hidden="true" />
              )}
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
              <button aria-label="Delete thread" type="button" onClick={() => onDelete(session.id)}>
                <AbstractIcon name="close" size={13} />
              </button>
            </UiTooltip>
          </div>
        </li>
      ))}
    </ul>
  )

  return (
    <TooltipProvider>
      <aside className="chat-sessions" aria-label="Chat sessions" data-shell-context="sidebar">
        <header className="chat-sidebar-head">
          <button className="chat-sidebar-home" type="button" onClick={onExit}>
            <AbstractIcon name="back" size={14} />
            <span>
              <strong>MARVI</strong>
              <small>CHAT</small>
            </span>
          </button>
          <UiTooltip label="Start a new conversation">
            <button
              className="chat-sidebar-new-icon"
              type="button"
              onClick={onNew}
              aria-label="New conversation"
            >
              <AbstractIcon name="plus" size={15} />
            </button>
          </UiTooltip>
        </header>

        <button className="chat-new" type="button" onClick={onNew}>
          <AbstractIcon name="plus" size={14} /> NEW CHAT
        </button>

        <label className="chat-session-search">
          <AbstractIcon name="search" size={13} />
          <input
            aria-label="Search conversations"
            placeholder="Search conversations"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>

        {recent.length > 0 || telegram.length === 0 ? (
          <>
            <div className="chat-sessions-label">
              <span>RECENT</span>
              <span>{recent.length}</span>
            </div>
            {recent.length === 0 ? (
              <span className="chat-sessions-empty">
                {sessions.length ? 'NO MATCHING CONVERSATIONS' : 'NO CONVERSATIONS YET'}
              </span>
            ) : (
              list(recent)
            )}
          </>
        ) : null}

        {telegram.length > 0 ? (
          <section aria-label="Telegram conversations" className="chat-session-group">
            <div className="chat-sessions-label">
              <span className="chat-sessions-channel">
                <TelegramLogo aria-hidden="true" className="chat-session-logo" />
                TELEGRAM
              </span>
              <span>{telegram.length}</span>
            </div>
            {list(telegram)}
          </section>
        ) : null}
        {timing}
        <footer className="chat-sidebar-foot">
          <UiTooltip label="Export conversation as Markdown">
            <button
              aria-label="Export conversation as Markdown"
              disabled={exportDisabled}
              onClick={onExport}
              type="button"
            >
              <AbstractIcon name="download" size={14} />
              EXPORT
            </button>
          </UiTooltip>
          <button onClick={onExit} type="button">
            <AbstractIcon name="back" size={14} />
            CONTROL CENTER
          </button>
        </footer>
      </aside>
    </TooltipProvider>
  )
}
