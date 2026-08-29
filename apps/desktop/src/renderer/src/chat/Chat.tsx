import { useStore } from '@nanostores/react'
import { useEffect } from 'react'

import { useChat } from './useChat'
import { useReadAloud } from './useReadAloud'
import { Composer } from './components/Composer'
import { ConfirmationBar } from './components/ConfirmationBar'
import { MessageList } from './components/MessageList'
import { Sessions } from './components/Sessions'
import './chat.css'
import { downloadTranscript } from './transcript'
import { MessageTiming } from '../components/message-timing'
import { $sessionMetrics, sessionTimingStats } from '../store/session-metrics'
import { setChatContextStatus } from '../store/chat-context'

/**
 * The typed conversation surface. Same Marvi as the voice session — same
 * identity, memory, tools, and confirmations — only the transport differs.
 *
 * The layout follows what every chat client settled on, for the same reasons:
 * the transcript owns the window, the composer is pinned to the bottom and
 * grows with the draft, and Chat replaces the general app navigation with a
 * purpose-built conversation index while this workspace is active.
 */
export function Chat({ onExit }: { onExit: () => void }): React.JSX.Element {
  const sessionMetrics = useStore($sessionMetrics)
  const {
    messages,
    threads,
    activeThreadId,
    attachments,
    context,
    notice,
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

  useEffect(() => {
    setChatContextStatus({
      context,
      pendingFiles: attachments.length,
      route: override.model
    })
    return () => setChatContextStatus({ context: null, pendingFiles: 0 })
  }, [attachments.length, context, override.model])

  return (
    <>
      <Sessions
        sessions={threads}
        activeId={activeThreadId}
        onSelect={(id) => void selectThread(id)}
        onNew={() => void createThread()}
        onRename={(id, title) => void renameThread(id, title)}
        onArchive={(id) => void archiveThread(id)}
        onDelete={(id) => void deleteThread(id)}
        onExit={onExit}
        onExport={() => downloadTranscript(messages)}
        exportDisabled={messages.length === 0}
        timing={
          <MessageTiming
            aria-label="Chat session metrics"
            className="chat-sidebar-timing"
            stats={sessionTimingStats(sessionMetrics)}
            streaming={busy}
          />
        }
      />
      <main className="content chat-workspace-content" data-shell-context="page">
        <section className="chat-page">
          {!available ? (
            <div className="chat-unavailable">
              NO PROVIDER CONNECTED — OPEN PROVIDERS TO CONNECT ONE
            </div>
          ) : null}

          <div className="chat-body-area">
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
                <ConfirmationBar
                  pending={pending}
                  onResolve={(decision) => void resolve(decision)}
                />
              ) : null}
              {notice ? (
                <div className="chat-notice" role="alert">
                  {notice}
                </div>
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
      </main>
    </>
  )
}
