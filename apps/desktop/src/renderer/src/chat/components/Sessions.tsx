import { Tr } from '../../store/locale'
import { useState } from 'react'
import type { ReactNode } from 'react'
import TelegramLogo from '@thesvg/react/telegram'

import type { ChatThread } from '../../../../shared/runtime'
import { AbstractIcon } from '../../components/abstract-icon'
import { TooltipProvider, UiTooltip } from '../../components/ui/tooltip'
import { formatRelative } from '../time'
import { $interfaceLocale, formatNumber, t } from '../../store/locale'
import { useStore } from '@nanostores/react'
import { MessageMatches } from './MessageMatches'

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
  const locale = useStore($interfaceLocale)
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
                aria-label={t('Thread title', locale)}
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
                <span className="chat-session-title" dir="auto">
                  {session.title}
                </span>
                <span className="chat-session-meta">
                  {formatNumber(session.message_count, locale)} {t('msgs', locale)} ·{' '}
                  {formatRelative(session.updated_at)}
                </span>
              </span>
            </button>
          )}
          <div className="chat-session-actions">
            <UiTooltip label={t('Rename thread', locale)}>
              <button
                aria-label={t('Rename thread', locale)}
                type="button"
                onClick={() => {
                  setTitle(session.title)
                  setEditing(session.id)
                }}
              >
                <AbstractIcon name="edit" size={13} />
              </button>
            </UiTooltip>
            <UiTooltip label={t('Archive thread', locale)}>
              <button
                aria-label={t('Archive thread', locale)}
                type="button"
                onClick={() => onArchive(session.id)}
              >
                <AbstractIcon name="archive" size={13} />
              </button>
            </UiTooltip>
            <UiTooltip label={t('Export as Markdown', locale)}>
              <button
                aria-label={t('Export thread as Markdown', locale)}
                type="button"
                onClick={() => void window.marvi?.exportChatThread(session.id)}
              >
                <AbstractIcon name="download" size={13} />
              </button>
            </UiTooltip>
            <UiTooltip label={t('Delete thread', locale)}>
              <button
                aria-label={t('Delete thread', locale)}
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
  )

  return (
    <TooltipProvider>
      <aside
        className="chat-sessions"
        aria-label={t('Chat sessions', locale)}
        data-shell-context="sidebar"
      >
        <header className="chat-sidebar-head">
          <button className="chat-sidebar-home" type="button" onClick={onExit}>
            <AbstractIcon name="back" size={14} />
            <span>
              <strong>
                <Tr text={'MARVI'} />
              </strong>
              <small>{t('Chat', locale)}</small>
            </span>
          </button>
          <UiTooltip label={t('Start a new conversation', locale)}>
            <button
              className="chat-sidebar-new-icon"
              type="button"
              onClick={onNew}
              aria-label={t('New conversation', locale)}
            >
              <AbstractIcon name="plus" size={15} />
            </button>
          </UiTooltip>
        </header>

        <button className="chat-new" type="button" onClick={onNew}>
          <AbstractIcon name="plus" size={14} /> {t('NEW CHAT', locale)}
        </button>

        <label className="chat-session-search">
          <AbstractIcon name="search" size={13} />
          <input
            aria-label={t('Search conversations', locale)}
            placeholder={t('Search conversations', locale)}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>

        <MessageMatches activeId={activeId} onSelect={onSelect} query={query} />

        {recent.length > 0 || telegram.length === 0 ? (
          <>
            <div className="chat-sessions-label">
              <span>{t('RECENT', locale)}</span>
              <span>{formatNumber(recent.length, locale)}</span>
            </div>
            {recent.length === 0 ? (
              <span className="chat-sessions-empty">
                {t(sessions.length ? 'NO MATCHING CONVERSATIONS' : 'NO CONVERSATIONS YET', locale)}
              </span>
            ) : (
              list(recent)
            )}
          </>
        ) : null}

        {telegram.length > 0 ? (
          <section aria-label={t('Telegram conversations', locale)} className="chat-session-group">
            <div className="chat-sessions-label">
              <span className="chat-sessions-channel">
                <TelegramLogo aria-hidden="true" className="chat-session-logo" />
                <Tr text={'TELEGRAM'} after />
              </span>
              <span>{formatNumber(telegram.length, locale)}</span>
            </div>
            {list(telegram)}
          </section>
        ) : null}
        {timing}
        <footer className="chat-sidebar-foot">
          <UiTooltip label={t('Export conversation as Markdown', locale)}>
            <button
              aria-label={t('Export conversation as Markdown', locale)}
              disabled={exportDisabled}
              onClick={onExport}
              type="button"
            >
              <AbstractIcon name="download" size={14} />
              {t('EXPORT', locale)}
            </button>
          </UiTooltip>
          <button onClick={onExit} type="button">
            <AbstractIcon name="back" size={14} />
            {t('CONTROL CENTER', locale)}
          </button>
        </footer>
      </aside>
    </TooltipProvider>
  )
}
