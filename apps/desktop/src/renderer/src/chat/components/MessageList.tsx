import { useEffect, useRef, useState } from 'react'

import { metaValue, type ChatMessage } from '../types'
import { AbstractIcon } from '../../components/abstract-icon'
import { TooltipProvider, UiTooltip } from '../../components/ui/tooltip'
import { AgentMessage } from './AgentMessage'
import { ErrorMessage } from './ErrorMessage'
import { ThinkingIndicator } from './ThinkingIndicator'
import { ToolCallsSection } from './ToolCallsSection'
import { UserMessage } from './UserMessage'

function MessageRow({
  message,
  onEdit,
  onRegenerate,
  readAloud
}: {
  message: ChatMessage
  onEdit?: (id: number, content: string) => void
  onRegenerate?: (id: number) => void
  readAloud?: {
    available: boolean
    readingId: number | null
    toggle: (id: number, content: string) => void
  }
}): React.JSX.Element {
  switch (message.role) {
    case 'user':
      return <UserMessage message={message} onEdit={onEdit} />
    case 'assistant':
      if (
        message.meta.streaming &&
        !message.content.trim() &&
        !metaValue(message.meta, 'reasoning')
      ) {
        return <ThinkingIndicator startedAt={message.at} />
      }
      return (
        <AgentMessage
          message={message}
          onRegenerate={onRegenerate}
          readAloud={
            readAloud
              ? {
                  available: readAloud.available,
                  reading: readAloud.readingId === message.id,
                  toggle: () => readAloud.toggle(message.id, message.content)
                }
              : undefined
          }
        />
      )
    case 'tool':
      return null
    default:
      return <ErrorMessage message={message} />
  }
}

export const STARTER_PROMPTS = [
  { code: 'ROOM', text: 'What is happening in the room right now?' },
  { code: 'MEMORY', text: 'What do you remember that could help me today?' },
  { code: 'PLAN', text: 'Help me turn my next goal into a clear plan.' }
] as const

export type MessageListItem =
  | { kind: 'message'; message: ChatMessage }
  | { kind: 'tools'; messages: ChatMessage[] }

export function groupToolMessages(messages: ChatMessage[]): MessageListItem[] {
  const items: MessageListItem[] = []
  for (const message of messages) {
    const last = items.at(-1)
    if (message.role === 'tool') {
      if (last?.kind === 'tools') last.messages.push(message)
      else items.push({ kind: 'tools', messages: [message] })
    } else items.push({ kind: 'message', message })
  }
  return items
}

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
  onSuggestion,
  onEdit,
  onRegenerate,
  readAloud
}: {
  messages: ChatMessage[]
  busy: boolean
  onSuggestion: (prompt: string) => void
  onEdit?: (id: number, content: string) => void
  onRegenerate?: (id: number) => void
  readAloud?: {
    available: boolean
    readingId: number | null
    announcement: string
    toggle: (id: number, content: string) => void
  }
}): React.JSX.Element {
  const viewport = useRef<HTMLDivElement | null>(null)
  const bottom = useRef<HTMLDivElement | null>(null)
  const [pinned, setPinned] = useState(true)
  const items = groupToolMessages(messages)

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
          {items.map((item) =>
            item.kind === 'tools' ? (
              <ToolCallsSection key={`tools-${item.messages[0].id}`} messages={item.messages} />
            ) : (
              <MessageRow message={item.message} key={item.message.id} onEdit={onEdit} onRegenerate={onRegenerate} readAloud={readAloud} />
            )
          )}
          <div ref={bottom} />
        </div>
      </div>
      {readAloud?.announcement ? (
        <span
          className={
            readAloud.readingId === null ? 'chat-speech-status' : 'chat-speech-status is-active'
          }
          aria-live="polite"
          role="status"
        >
          {readAloud.announcement}
        </span>
      ) : null}
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
