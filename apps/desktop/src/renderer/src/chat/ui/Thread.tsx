/**
 * The transcript: viewport, scroller, centred column, messages.
 *
 * The element names are not decoration, they are the contract `chat.css`
 * already owns. `chat-thread-viewport` is the positioning context the
 * scroll-to-bottom button anchors to, `chat-log` is the thing that actually
 * scrolls, and `chat-thread-content` is the 720px centred column. Rendering
 * the SDK's primitives without those wrappers is what made every message span
 * the whole window.
 *
 * The composer is deliberately *not* here. It is a sibling of this viewport in
 * `chat-main`, which is where it was before and what its own gradient assumes;
 * putting it inside the scroll viewport made it sticky within the scroller and
 * stretched it across the window.
 */

import { ThreadPrimitive } from '@assistant-ui/react'

import { AbstractIcon } from '../../components/abstract-icon'
import { marviLogo } from '../../components/ui/marvi-logo'
import { AssistantMessage, UserEditComposer, UserMessage } from './Messages'
import type { ReadAloud } from './parts'

/** The three openers on an empty thread. Prompts, not instructions. */
const STARTER_PROMPTS = [
  { code: 'ROOM', text: 'What is happening in the room right now?' },
  { code: 'MEMORY', text: 'What do you remember that could help me today?' },
  { code: 'PLAN', text: 'Help me turn my next goal into a clear plan.' }
] as const

function EmptyState(): React.JSX.Element {
  return (
    <div className="chat-empty">
      {/* Branding, and the only place it appears at this size: an empty thread
          has nothing else in it, and a logo over a conversation in progress is
          a watermark nobody asked for. */}
      <img alt="" aria-hidden="true" className="chat-empty-logo" src={marviLogo} />
      <div className="chat-empty-mark" aria-hidden="true">
        <span>MARVI</span>
      </div>
      <h2>What should we work through?</h2>
      <p>One assistant across voice, memory, tools, and the room.</p>
      <div className="chat-starters" aria-label="Starter prompts">
        {STARTER_PROMPTS.map((prompt) => (
          <ThreadPrimitive.Suggestion key={prompt.code} method="replace" prompt={prompt.text}>
            <span>{prompt.code}</span>
            {prompt.text}
          </ThreadPrimitive.Suggestion>
        ))}
      </div>
    </div>
  )
}

export function Thread({ readAloud }: { readAloud?: ReadAloud }): React.JSX.Element {
  return (
    <ThreadPrimitive.Root className="chat-thread-viewport">
      <ThreadPrimitive.Viewport className="chat-log">
        <div className="chat-thread-content">
          <ThreadPrimitive.Empty>
            <EmptyState />
          </ThreadPrimitive.Empty>
          <ThreadPrimitive.Messages>
            {({ message }) => {
              if (message.role !== 'user') {
                return <AssistantMessage message={message} readAloud={readAloud} />
              }
              // The render-function form of `Messages` has no edit-composer
              // slot, so the swap happens here. Without it the Edit button
              // sets a state nothing renders.
              return message.composer.isEditing ? (
                <UserEditComposer />
              ) : (
                <UserMessage message={message} />
              )
            }}
          </ThreadPrimitive.Messages>
        </div>
      </ThreadPrimitive.Viewport>
      {/* Absolutely positioned against the viewport, and hidden by CSS while
          the thread is already at the bottom -- the primitive disables itself
          rather than unmounting. */}
      <ThreadPrimitive.ScrollToBottom
        aria-label="Scroll to latest message"
        className="chat-scroll-bottom"
      >
        <AbstractIcon name="down" size={16} />
      </ThreadPrimitive.ScrollToBottom>
    </ThreadPrimitive.Root>
  )
}
