import { useState } from 'react'
import { useStore } from '@nanostores/react'

import { formatRelative, titleFromMessages } from './time'
import { useChat } from './useChat'
import { Composer } from './components/Composer'
import { ConfirmationBar } from './components/ConfirmationBar'
import { MessageList } from './components/MessageList'
import { Sessions, type Session } from './components/Sessions'
import './chat.css'
import { MessageTiming } from '../components/message-timing'
import { $sessionMetrics, sessionTimingStats } from '../store/session-metrics'

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
    busy,
    available,
    draft,
    pending,
    setDraft,
    send,
    clear,
    resolve,
    cancel,
    override,
    setOverride
  } = useChat()
  const [drawer, setDrawer] = useState(false)

  const last = messages[messages.length - 1]
  const session: Session = {
    id: 'current',
    title: titleFromMessages(messages),
    updatedAt: formatRelative(last?.at ?? ''),
    messageCount: messages.length
  }

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
        <span className="chat-bar-title">{session.title}</span>
        <MessageTiming
          aria-label="Chat session metrics"
          className="chat-session-timing"
          stats={sessionTimingStats(sessionMetrics)}
          streaming={busy}
        />
        <button
          className="chat-bar-button"
          disabled={busy || messages.length === 0}
          onClick={() => void clear()}
          type="button"
        >
          NEW
        </button>
      </header>

      {!available ? (
        <div className="chat-unavailable">
          NO PROVIDER CONNECTED — OPEN PROVIDERS TO CONNECT ONE
        </div>
      ) : null}

      <div className="chat-body-area">
        {drawer ? (
          <Sessions
            sessions={[session]}
            activeId="current"
            onSelect={() => setDrawer(false)}
            onNew={() => {
              void clear()
              setDrawer(false)
            }}
          />
        ) : null}

        <div className="chat-main">
          <MessageList messages={messages} busy={busy} />
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
            override={override}
            onOverrideChange={setOverride}
          />
        </div>
      </div>
    </section>
  )
}
