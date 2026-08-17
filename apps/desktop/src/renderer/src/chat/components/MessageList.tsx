import { useEffect, useRef } from 'react'

import type { ChatMessage } from '../types'
import { AgentMessage } from './AgentMessage'
import { ErrorMessage } from './ErrorMessage'
import { ThinkingIndicator } from './ThinkingIndicator'
import { ToolMessage } from './ToolMessage'
import { UserMessage } from './UserMessage'

function MessageRow({ message }: { message: ChatMessage }): React.JSX.Element {
  switch (message.role) {
    case 'user':
      return <UserMessage message={message} />
    case 'assistant':
      return <AgentMessage message={message} />
    case 'tool':
      return <ToolMessage message={message} />
    default:
      return <ErrorMessage message={message} />
  }
}

function EmptyState(): React.JSX.Element {
  return (
    <div className="chat-empty">
      <span className="chat-empty-glyph">MARVI</span>
      <p>Same Marvi as the voice session — same identity, memory, tools, and confirmations.</p>
      <p className="chat-empty-hint">Ask about a file, a memory, or something you want done.</p>
    </div>
  )
}

export function MessageList({
  messages,
  busy
}: {
  messages: ChatMessage[]
  busy: boolean
}): React.JSX.Element {
  const bottom = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy])

  return (
    <div className="chat-log" role="log" aria-live="polite" aria-label="Conversation">
      {messages.length === 0 && !busy ? <EmptyState /> : null}
      {messages.map((message) => (
        <MessageRow message={message} key={message.id} />
      ))}
      {busy ? <ThinkingIndicator /> : null}
      <div ref={bottom} />
    </div>
  )
}
