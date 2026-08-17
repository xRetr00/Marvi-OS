import { formatRelative, titleFromMessages } from './time'
import { useChat } from './useChat'
import { Composer } from './components/Composer'
import { ConfirmationBar } from './components/ConfirmationBar'
import { MessageList } from './components/MessageList'
import { Sessions, type Session } from './components/Sessions'
import './chat.css'

/**
 * The typed conversation surface. Same Marvi as the voice session — same
 * identity, memory, tools, and confirmations — only the transport differs.
 */
export function Chat(): React.JSX.Element {
  const { messages, busy, available, draft, pending, setDraft, send, clear, resolve } = useChat()

  const last = messages[messages.length - 1]
  const session: Session = {
    id: 'current',
    title: titleFromMessages(messages),
    updatedAt: formatRelative(last?.at ?? ''),
    messageCount: messages.length
  }

  return (
    <section className="single-page panel chat-page">
      <div className="panel-label">{'// CHAT'}</div>
      <div className="chat-layout">
        <Sessions
          sessions={[session]}
          activeId="current"
          onSelect={() => {}}
          onNew={() => void clear()}
        />
        <div className="chat-main">
          {!available ? (
            <div className="chat-unavailable">
              NO PROVIDER CONNECTED — OPEN PROVIDERS TO CONNECT ONE
            </div>
          ) : null}
          <MessageList messages={messages} busy={busy} />
          {pending ? (
            <ConfirmationBar pending={pending} onResolve={(decision) => void resolve(decision)} />
          ) : null}
          <Composer
            draft={draft}
            busy={busy}
            available={available}
            canClear={messages.length > 0}
            onDraftChange={setDraft}
            onSend={() => void send()}
            onClear={() => void clear()}
          />
        </div>
      </div>
    </section>
  )
}
