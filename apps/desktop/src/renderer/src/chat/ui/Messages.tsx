/**
 * A turn, drawn on assistant-ui's primitives and Marvi's stylesheet.
 *
 * The markup keeps the class names the existing `chat.css` already targets --
 * `chat-turn`, `chat-user`, `chat-assistant`, `chat-turn-actions` -- so the
 * SDK supplies behaviour (hover state, branch navigation, edit composer,
 * copy) and nothing supplies a second look.
 *
 * Read-aloud is the one action that is not an `ActionBarPrimitive`. Wiring it
 * through a `SpeechSynthesisAdapter` would mean reimplementing `useReadAloud`
 * inside an adapter interface to end up in the same place, so it stays a plain
 * button reading the message text it is rendered beside.
 */

import type { MessageState } from '@assistant-ui/react'
import {
  ActionBarPrimitive,
  BranchPickerPrimitive,
  ComposerPrimitive,
  MessagePrimitive
} from '@assistant-ui/react'

import { AbstractIcon } from '../../components/abstract-icon'
import { MarviAvatar } from '../../components/ui/avatar'
import { TooltipProvider, UiTooltip } from '../../components/ui/tooltip'
import { formatTime } from '../time'
import { AttachmentPreview } from '../components/AttachmentPreview'
import { CopyMessageAction } from '../components/MessageAction'
import { AssistantParts } from './AssistantParts'
import { messageText } from './message-text'
import { MESSAGE_PART_COMPONENTS } from './parts'
import type { ReadAloud } from './parts'

function createdAt(message: MessageState): string {
  return (message.createdAt ?? new Date()).toISOString()
}

function BranchPicker({ className }: { className?: string }): React.JSX.Element {
  return (
    <BranchPickerPrimitive.Root
      className={className ? `chat-branches ${className}` : 'chat-branches'}
      hideWhenSingleBranch
    >
      <BranchPickerPrimitive.Previous aria-label="Previous version" className="chat-branch-step">
        <AbstractIcon name="back" size={12} />
      </BranchPickerPrimitive.Previous>
      <span className="chat-branch-count">
        <BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count />
      </span>
      <BranchPickerPrimitive.Next aria-label="Next version" className="chat-branch-step">
        <AbstractIcon name="forward" size={12} />
      </BranchPickerPrimitive.Next>
    </BranchPickerPrimitive.Root>
  )
}

/**
 * Your turn, as assistant-ui draws it: a bubble on the right that hugs its
 * text, with the actions tucked to its left and the branch picker beneath.
 *
 * It used to be a full-width card, which read as a section header rather than
 * as something *you* said -- the two speakers looked like one column of blocks
 * stacked on each other. The two-column grid is the whole trick: the bubble
 * takes the second column and sizes to content, the first column absorbs the
 * slack and gives the action row somewhere to live.
 */
export function UserMessage({ message }: { message: MessageState }): React.JSX.Element {
  return (
    <MessagePrimitive.Root
      aria-label="Your message"
      className="chat-turn chat-user"
      data-role="user"
      data-slot="chat-user-message"
    >
      <span className="sr-only">YOU</span>
      <div className="chat-user-surface" data-slot="chat-user-surface">
        <div className="chat-body chat-user-text">
          <MessagePrimitive.Parts components={MESSAGE_PART_COMPONENTS} />
        </div>
        {message.attachments?.length ? (
          // Marvi's own preview rather than `MessagePrimitive.Attachments`: it
          // resolves a thumbnail through the preload bridge by attachment id,
          // which an SDK attachment part has no way to reach.
          <div className="chat-message-files">
            {message.attachments.map((attachment) => (
              <AttachmentPreview
                attachment={{
                  id: attachment.id,
                  name: attachment.name,
                  media_type: attachment.contentType ?? 'application/octet-stream',
                  size: 0,
                  kind: attachment.contentType?.startsWith('image/') ? 'image' : 'document'
                }}
                key={attachment.id}
              />
            ))}
          </div>
        ) : null}
        {/* Inside the bubble, on its own row. Floating them off to the left
            left the actions stranded in empty space with nothing to attach
            them to, and on a wide window they ended up nowhere near the
            message they belonged to. */}
        <TooltipProvider>
          <div className="chat-turn-actions chat-user-actions">
            <span className="chat-message-age">{formatTime(createdAt(message))}</span>
            <BranchPicker />
            <ActionBarPrimitive.Root className="chat-action-bar">
              <UiTooltip label="Edit and branch from this message">
                <ActionBarPrimitive.Edit
                  aria-label="Edit message"
                  className="chat-message-action"
                  type="button"
                >
                  <AbstractIcon name="edit" size={13} />
                </ActionBarPrimitive.Edit>
              </UiTooltip>
              {/* Marvi's own copy, not `ActionBarPrimitive.Copy`.
                  The SDK's version goes through `navigator.clipboard`, which
                  needs a secure context and a focused document -- in this
                  window it rejects and the button does nothing at all. The
                  main process owns a real clipboard, and this is the same path
                  the code blocks in a reply already use. */}
              <CopyMessageAction content={messageText(message)} label="Copy message" />
            </ActionBarPrimitive.Root>
          </div>
        </TooltipProvider>
      </div>
    </MessagePrimitive.Root>
  )
}

/**
 * The same bubble, opened for editing.
 *
 * `ActionBarPrimitive.Edit` only puts the message's composer into editing
 * state -- something still has to render that composer, and nothing did, which
 * is why the pencil appeared to do nothing at all. Inside a message scope the
 * composer primitives bind to *that message's* editor, so this is the same
 * three components the main composer uses.
 */
export function UserEditComposer(): React.JSX.Element {
  return (
    <MessagePrimitive.Root className="chat-turn chat-user is-editing">
      <ComposerPrimitive.Root className="chat-user-surface chat-message-edit">
        <ComposerPrimitive.Input aria-label="Edit message" autoFocus />
        <div className="chat-message-edit-actions">
          <ComposerPrimitive.Cancel className="chat-edit-cancel">CANCEL</ComposerPrimitive.Cancel>
          <ComposerPrimitive.Send className="chat-edit-send">SEND EDIT</ComposerPrimitive.Send>
        </div>
      </ComposerPrimitive.Root>
    </MessagePrimitive.Root>
  )
}

export function AssistantMessage({
  message,
  readAloud
}: {
  message: MessageState
  readAloud?: ReadAloud
}): React.JSX.Element {
  const streaming = message.status?.type === 'running'
  const failed = message.status?.type === 'incomplete' && message.status.reason === 'error'
  const text = messageText(message)
  const id = Number(message.id)

  return (
    <MessagePrimitive.Root
      aria-busy={streaming ? 'true' : undefined}
      aria-label="Marvi response"
      className={failed ? 'chat-turn chat-assistant chat-failed' : 'chat-turn chat-assistant'}
    >
      <MarviAvatar className="chat-turn-avatar" />
      <div className="chat-turn-column">
        <span className="sr-only">MARVI</span>
        <AssistantParts message={message} />
        <MessagePrimitive.Error>
          <div className="chat-error-body" role="alert">
            <ErrorText message={message} />
          </div>
        </MessagePrimitive.Error>
        <TooltipProvider>
          <div className="chat-turn-foot">
            <div className="chat-turn-actions">
              <span className="chat-message-age">{formatTime(createdAt(message))}</span>
              <BranchPicker />
              {readAloud?.available && !streaming && text ? (
                <UiTooltip label={readAloud.readingId === id ? 'Stop reading' : 'Read aloud'}>
                  <button
                    aria-label={readAloud.readingId === id ? 'Stop reading' : 'Read aloud'}
                    aria-pressed={readAloud.readingId === id}
                    className="chat-message-action"
                    onClick={() => readAloud.toggle(id, text)}
                    type="button"
                  >
                    <AbstractIcon
                      name={readAloud.readingId === id ? 'stop' : 'speaker'}
                      size={14}
                    />
                  </button>
                </UiTooltip>
              ) : null}
              <ActionBarPrimitive.Root className="chat-action-bar" hideWhenRunning>
                <UiTooltip label="Regenerate on a new branch">
                  <ActionBarPrimitive.Reload
                    aria-label="Regenerate response"
                    className="chat-message-action"
                    type="button"
                  >
                    <AbstractIcon name="regenerate" size={14} />
                  </ActionBarPrimitive.Reload>
                </UiTooltip>
                <CopyMessageAction content={text} label="Copy response" />
              </ActionBarPrimitive.Root>
            </div>
          </div>
        </TooltipProvider>
      </div>
    </MessagePrimitive.Root>
  )
}

function ErrorText({ message }: { message: MessageState }): React.JSX.Element | null {
  const status = message.status
  if (!status || status.type !== 'incomplete') return null
  return <>{String(status.error ?? 'Something went wrong.')}</>
}
