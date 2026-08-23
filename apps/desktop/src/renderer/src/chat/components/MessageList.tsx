import { useEffect, useRef, useState } from 'react'

import type { ChatMessage } from '../types'
import { AbstractIcon } from '../../components/abstract-icon'
import { TooltipProvider, UiTooltip } from '../../components/ui/tooltip'
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

export const STARTER_PROMPTS = [
  { code: 'ROOM', text: 'What is happening in the room right now?' },
  { code: 'MEMORY', text: 'What do you remember that could help me today?' },
  { code: 'PLAN', text: 'Help me turn my next goal into a clear plan.' }
] as const

function EmptyState({
  onSuggestion
}: {
  onSuggestion: (prompt: string) => void
}): React.JSX.Element {
  return (
    <div className="chat-empty">
      <div className="chat-empty-mark" aria-hidden="true">
        <span>+</span>
        <span>MARVI</span>
        <span>+</span>
      </div>
      <h2>What should we work through?</h2>
      <p>One assistant across voice, memory, tools, and the room.</p>
      <div className="chat-starters" aria-label="Starter prompts">
        {STARTER_PROMPTS.map((prompt) => (
          <button key={prompt.code} type="button" onClick={() => onSuggestion(prompt.text)}>
            <span>{prompt.code}</span>
            {prompt.text}
          </button>
        ))}
      </div>
    </div>
  )
}

export function MessageList({
  messages,
  busy,
  onSuggestion
}: {
  messages: ChatMessage[]
  busy: boolean
  onSuggestion: (prompt: string) => void
}): React.JSX.Element {
  const viewport = useRef<HTMLDivElement | null>(null)
  const bottom = useRef<HTMLDivElement | null>(null)
  const [pinned, setPinned] = useState(true)

  useEffect(() => {
    if (pinned) bottom.current?.scrollIntoView({ behavior: busy ? 'auto' : 'smooth' })
  }, [messages, busy, pinned])

  const updatePinned = (): void => {
    const node = viewport.current
    if (!node) return
    setPinned(node.scrollHeight - node.scrollTop - node.clientHeight < 56)
  }

  const scrollToBottom = (): void => {
    setPinned(true)
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <div className="chat-thread-viewport">
      <div
        className="chat-log"
        ref={viewport}
        role="log"
        aria-live="polite"
        aria-label="Conversation"
        onScroll={updatePinned}
      >
        <div className="chat-thread-content">
          {messages.length === 0 && !busy ? <EmptyState onSuggestion={onSuggestion} /> : null}
          {messages.map((message) => (
            <MessageRow message={message} key={message.id} />
          ))}
          {busy ? <ThinkingIndicator /> : null}
          <div ref={bottom} />
        </div>
      </div>
      {!pinned ? (
        <TooltipProvider>
          <UiTooltip label="Scroll to latest message">
            <button
              aria-label="Scroll to latest message"
              className="chat-scroll-bottom"
              onClick={scrollToBottom}
              type="button"
            >
              <AbstractIcon name="down" size={16} />
            </button>
          </UiTooltip>
        </TooltipProvider>
      ) : null}
    </div>
  )
}
