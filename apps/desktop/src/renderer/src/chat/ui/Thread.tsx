/**
 * The transcript: viewport, messages, composer.
 *
 * `ThreadPrimitive.Viewport` owns the scroll behaviour that used to be a
 * `useEffect` chasing `scrollHeight` -- it sticks to the bottom while a reply
 * streams and lets go the moment somebody scrolls up, which is the behaviour
 * every chat client has and the one that is fiddly to write twice.
 */

import { ThreadPrimitive } from '@assistant-ui/react'

import type { ChatAttachment } from '../../../../shared/runtime'
import { AbstractIcon } from '../../components/abstract-icon'
import { marviLogo } from '../../components/ui/avatar'
import { Composer } from './Composer'
import { AssistantMessage, UserMessage } from './Messages'
import type { ReadAloud } from './parts'

/** The four openers on an empty thread. Prompts, not instructions. */
const SUGGESTIONS = [
  'What can you do?',
  'Summarise my day',
  'What did we talk about last?',
  'Show me what you remember'
]

export function Thread({
  available,
  busy,
  attachments,
  onFiles,
  onRemoveAttachment,
  override,
  onOverrideChange,
  readAloud,
  footer
}: {
  available: boolean
  busy: boolean
  attachments: ChatAttachment[]
  onFiles: (files: FileList | File[]) => void
  onRemoveAttachment: (id: string) => void
  override: { provider?: string; model?: string; effort?: string }
  onOverrideChange: (next: { provider?: string; model?: string; effort?: string }) => void
  readAloud?: ReadAloud
  footer?: React.ReactNode
}): React.JSX.Element {
  return (
    <ThreadPrimitive.Root className="chat-thread">
      <ThreadPrimitive.Viewport className="chat-thread-viewport">
        <ThreadPrimitive.Empty>
          <div className="chat-empty">
            {/* Branding, and the only place it appears at this size: an empty
                thread has nothing else in it, and a logo over a conversation
                in progress is a watermark nobody asked for. */}
            <img alt="Marvi" className="chat-empty-logo" src={marviLogo} />
            <p className="chat-empty-lead">Ask Marvi anything.</p>
            <div className="chat-suggestions">
              {SUGGESTIONS.map((prompt) => (
                <ThreadPrimitive.Suggestion
                  className="chat-suggestion"
                  key={prompt}
                  method="replace"
                  prompt={prompt}
                >
                  {prompt}
                </ThreadPrimitive.Suggestion>
              ))}
            </div>
          </div>
        </ThreadPrimitive.Empty>

        <ThreadPrimitive.Messages>
          {({ message }) =>
            message.role === 'user' ? (
              <UserMessage message={message} />
            ) : (
              <AssistantMessage message={message} readAloud={readAloud} />
            )
          }
        </ThreadPrimitive.Messages>

        <ThreadPrimitive.ViewportFooter className="chat-thread-foot">
          <ThreadPrimitive.ScrollToBottom
            aria-label="Scroll to the latest message"
            className="chat-scroll-bottom"
          >
            <AbstractIcon name="down" size={14} />
          </ThreadPrimitive.ScrollToBottom>
          {footer}
          <Composer
            attachments={attachments}
            available={available}
            busy={busy}
            onFiles={onFiles}
            onOverrideChange={onOverrideChange}
            onRemoveAttachment={onRemoveAttachment}
            override={override}
          />
        </ThreadPrimitive.ViewportFooter>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  )
}
