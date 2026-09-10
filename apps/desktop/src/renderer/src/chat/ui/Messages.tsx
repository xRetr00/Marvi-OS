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
import { ActionBarPrimitive, BranchPickerPrimitive, MessagePrimitive } from '@assistant-ui/react'

import { AbstractIcon } from '../../components/abstract-icon'
import { MarviAvatar } from '../../components/ui/avatar'
import { TooltipProvider, UiTooltip } from '../../components/ui/tooltip'
import { formatTime } from '../time'
import { AttachmentPreview } from '../components/AttachmentPreview'
import { messageText } from './message-text'
import { MESSAGE_PART_COMPONENTS } from './parts'
import type { ReadAloud } from './parts'

function createdAt(message: MessageState): string {
  return (message.createdAt ?? new Date()).toISOString()
}

function BranchPicker(): React.JSX.Element {
  return (
    <BranchPickerPrimitive.Root className="chat-branches" hideWhenSingleBranch>
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
      </div>
      <TooltipProvider>
        <div className="chat-turn-actions">
          <span className="chat-message-age">{formatTime(createdAt(message))}</span>
          <BranchPicker />
          <ActionBarPrimitive.Root className="chat-action-bar">
            <UiTooltip label="Edit and branch from this message">
              <ActionBarPrimitive.Edit
                aria-label="Edit message"
                className="chat-message-action"
                type="button"
              >
                <AbstractIcon name="edit" size={14} />
              </ActionBarPrimitive.Edit>
            </UiTooltip>
            <UiTooltip label="Copy message">
              <ActionBarPrimitive.Copy
                aria-label="Copy message"
                className="chat-message-action"
                type="button"
              >
                <AbstractIcon name="copy" size={14} />
              </ActionBarPrimitive.Copy>
            </UiTooltip>
          </ActionBarPrimitive.Root>
        </div>
      </TooltipProvider>
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
        <MessagePrimitive.Parts components={MESSAGE_PART_COMPONENTS} />
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
                <UiTooltip label="Copy response">
                  <ActionBarPrimitive.Copy
                    aria-label="Copy response"
                    className="chat-message-action"
                    type="button"
                  >
                    <AbstractIcon name="copy" size={14} />
                  </ActionBarPrimitive.Copy>
                </UiTooltip>
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
