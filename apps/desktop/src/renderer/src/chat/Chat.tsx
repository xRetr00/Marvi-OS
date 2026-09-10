import { useStore } from '@nanostores/react'
import { useEffect } from 'react'
import { AssistantRuntimeProvider } from '@assistant-ui/react'

import { useChat } from './useChat'
import { useReadAloud } from './useReadAloud'
import { useMarviRuntime } from './runtime/useMarviRuntime'
import { ConfirmationBar } from './components/ConfirmationBar'
import { Sessions } from './components/Sessions'
import { Thread } from './ui/Thread'
import './chat.css'
import './ui/ask.css'
import { downloadTranscript } from './transcript'
import { MessageTiming } from '../components/message-timing'
import { $sessionMetrics, sessionTimingStats } from '../store/session-metrics'
import { setChatContextStatus } from '../store/chat-context'

/**
 * The typed conversation surface. Same Marvi as the voice session — same
 * identity, memory, tools, and confirmations — only the transport differs.
 *
 * The transcript, the composer and every message action run on assistant-ui:
 * `useChat` keeps the store and the IPC, `useMarviRuntime` presents it as an
 * external-store runtime, and the components under `ui/` draw it with Marvi's
 * own stylesheet. The sidebar stays a purpose-built conversation index rather
 * than a `ThreadListPrimitive`, because it carries session timing and export
 * that a thread list has no place for.
 */
export function Chat({ onExit }: { onExit: () => void }): React.JSX.Element {
  const sessionMetrics = useStore($sessionMetrics)
  const chat = useChat()
  const runtime = useMarviRuntime(chat)
  const readAloud = useReadAloud(chat.activeThreadId)

  useEffect(() => {
    setChatContextStatus({
      context: chat.context,
      pendingFiles: chat.attachments.length,
      route: chat.override.model
    })
    return () => setChatContextStatus({ context: null, pendingFiles: 0 })
  }, [chat.attachments.length, chat.context, chat.override.model])

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <Sessions
        sessions={chat.threads}
        activeId={chat.activeThreadId}
        onSelect={(id) => void chat.selectThread(id)}
        onNew={() => void chat.createThread()}
        onRename={(id, title) => void chat.renameThread(id, title)}
        onArchive={(id) => void chat.archiveThread(id)}
        onDelete={(id) => void chat.deleteThread(id)}
        onExit={onExit}
        onExport={() => downloadTranscript(chat.messages)}
        exportDisabled={chat.messages.length === 0}
        timing={
          <MessageTiming
            aria-label="Chat session metrics"
            className="chat-sidebar-timing"
            stats={sessionTimingStats(sessionMetrics)}
            streaming={chat.busy}
          />
        }
      />
      <main className="content chat-workspace-content" data-shell-context="page">
        <section className="chat-page">
          {!chat.available ? (
            <div className="chat-unavailable">
              NO PROVIDER CONNECTED — OPEN PROVIDERS TO CONNECT ONE
            </div>
          ) : null}

          <div className="chat-body-area">
            <div className="chat-main">
              <Thread
                attachments={chat.attachments}
                available={chat.available}
                busy={chat.busy}
                footer={
                  <>
                    {chat.pending ? (
                      <ConfirmationBar
                        pending={chat.pending}
                        onResolve={(decision) => void chat.resolve(decision)}
                      />
                    ) : null}
                    {chat.notice ? (
                      <div className="chat-notice" role="alert">
                        {chat.notice}
                      </div>
                    ) : null}
                  </>
                }
                onFiles={(files) => void chat.addAttachments(files)}
                onOverrideChange={chat.setOverride}
                onRemoveAttachment={(id) => void chat.removeAttachment(id)}
                override={chat.override}
                readAloud={{
                  available: readAloud.available,
                  readingId: readAloud.readingId,
                  toggle: readAloud.toggle
                }}
              />
            </div>
          </div>
        </section>
      </main>
    </AssistantRuntimeProvider>
  )
}
