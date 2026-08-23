import { useState } from 'react'
import { useStore } from '@nanostores/react'

import { useChat } from './useChat'
import { useReadAloud } from './useReadAloud'
import { Composer } from './components/Composer'
import { ConfirmationBar } from './components/ConfirmationBar'
import { MessageList } from './components/MessageList'
import { Sessions } from './components/Sessions'
import './chat.css'
import { MessageTiming } from '../components/message-timing'
import { AbstractIcon } from '../components/abstract-icon'
import { UiTooltip } from '../components/ui/tooltip'
import { $sessionMetrics, sessionTimingStats } from '../store/session-metrics'
import { downloadTranscript } from './transcript'

/**
 * The typed conversation surface. Same Marvi as the voice session — same
 * identity, memory, tools, and confirmations — only the transport differs.
 *
 * The layout follows what every chat client settled on, for the same reasons:
 * the transcript owns the window, the composer is pinned to the bottom and
 * grows with the draft, and the session list is a drawer rather than a column
 * permanently spending a fifth of the width on one entry.
 */
export function Chat(): React.JSX.Element {
  const sessionMetrics = useStore($sessionMetrics)
  const {
    messages,
    threads,
    activeThreadId,
    attachments,
    busy,
    available,
    draft,
    pending,
    setDraft,
    send,
    edit,
    regenerate,
    createThread,
    selectThread,
    renameThread,
    archiveThread,
    deleteThread,
    addAttachments,
    removeAttachment,
    resolve,
    cancel,
    override,
    setOverride
  } = useChat()
  const readAloud = useReadAloud(activeThreadId)
  const [drawer, setDrawer] = useState(false)

  const activeThread = threads.find((thread) => thread.id === activeThreadId)

  return (
    <section className="chat-page">
      <header className="chat-bar">
        <button
          aria-expanded={drawer}
          className="chat-bar-button"
          onClick={() => setDrawer(!drawer)}
          type="button"
        >
          {drawer ? 'CLOSE' : 'SESSIONS'}
        </button>
        <span className="chat-bar-title">{activeThread?.title ?? 'New conversation'}</span>
        <MessageTiming
          aria-label="Chat session metrics"
          className="chat-session-timing"
          stats={sessionTimingStats(sessionMetrics)}
          streaming={busy}
        />
        <div className="chat-bar-actions">
          <UiTooltip label="Export conversation as Markdown">
            <button
              aria-label="Export conversation as Markdown"
              className="chat-bar-icon"
              disabled={messages.length === 0}
              onClick={() => downloadTranscript(messages)}
              type="button"
            >
              <AbstractIcon name="download" size={15} />
            </button>
          </UiTooltip>
          <button
            className="chat-bar-button"
            disabled={busy}
            onClick={() => void createThread()}
            type="button"
          >
            NEW
          </button>
        </div>
      </header>

      {!available ? (
        <div className="chat-unavailable">
          NO PROVIDER CONNECTED — OPEN PROVIDERS TO CONNECT ONE
        </div>
      ) : null}

      <div className="chat-body-area">
        {drawer ? (
          <Sessions
            sessions={threads}
            activeId={activeThreadId}
            onSelect={(id) => {
              void selectThread(id)
              setDrawer(false)
            }}
            onNew={() => {
              void createThread()
              setDrawer(false)
            }}
            onRename={(id, title) => void renameThread(id, title)}
            onArchive={(id) => void archiveThread(id)}
            onDelete={(id) => void deleteThread(id)}
          />
        ) : null}

        <div className="chat-main">
          <MessageList
            messages={messages}
            busy={busy}
            onSuggestion={setDraft}
            onEdit={(id, content) => void edit(id, content)}
            onRegenerate={(id) => void regenerate(id)}
            readAloud={readAloud}
          />
          {pending ? (
            <ConfirmationBar pending={pending} onResolve={(decision) => void resolve(decision)} />
          ) : null}
          <Composer
            draft={draft}
            busy={busy}
            available={available}
            onDraftChange={setDraft}
            onSend={() => void send()}
            onCancel={() => void cancel()}
            attachments={attachments}
            onFiles={(files) => void addAttachments(files)}
            onRemoveAttachment={(id) => void removeAttachment(id)}
            override={override}
            onOverrideChange={setOverride}
          />
        </div>
      </div>
    </section>
  )
}
