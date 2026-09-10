/**
 * The field, on the SDK's composer.
 *
 * The draft now lives in the runtime rather than in `useChat`, which is what
 * makes the rest of assistant-ui work: an edit composer, a suggestion, and a
 * `clarify` answer all write into the same place the send button reads from.
 * Enter-to-send, Shift+Enter, auto-grow and refocus-after-run come with
 * `ComposerPrimitive.Input`; they used to be hand-rolled here.
 *
 * Everything Marvi-specific stays: the attach control, dictation, and the
 * per-conversation model picker.
 */

import { useCallback, useRef, useState } from 'react'
import {
  ComposerPrimitive,
  ThreadPrimitive,
  unstable_useComposerInput
} from '@assistant-ui/react'

import type { ChatAttachment } from '../../../../shared/runtime'
import { AbstractIcon } from '../../components/abstract-icon'
import { GlyphSpinner } from '../../components/ui/glyph-spinner'
import { TooltipProvider, UiTooltip } from '../../components/ui/tooltip'
import { PendingAttachment } from '../components/PendingAttachment'
import { SessionModel } from './SessionModel'
import { useDictation } from '../useDictation'

export function Composer({
  available,
  busy,
  attachments = [],
  onFiles,
  onRemoveAttachment,
  override,
  onOverrideChange
}: {
  available: boolean
  busy: boolean
  attachments?: ChatAttachment[]
  onFiles?: (files: FileList | File[]) => void
  onRemoveAttachment?: (id: string) => void
  override?: { provider?: string; model?: string; effort?: string }
  onOverrideChange?: (next: { provider?: string; model?: string; effort?: string }) => void
}): React.JSX.Element {
  const fileInput = useRef<HTMLInputElement | null>(null)
  const [focused, setFocused] = useState(false)
  const composer = unstable_useComposerInput()
  const appendDictation = useCallback(
    (text: string) => {
      const current = composer.value
      composer.setText(`${current}${current.trim() ? ' ' : ''}${text}`)
    },
    [composer]
  )
  const dictation = useDictation(appendDictation)
  const active = focused || busy || Boolean(composer.value.trim())

  return (
    <TooltipProvider>
      <ComposerPrimitive.Root
        className="chat-compose"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault()
          if (event.dataTransfer.files.length) onFiles?.(event.dataTransfer.files)
        }}
      >
        <div className="chat-compose-field" data-active={active ? 'true' : 'false'}>
          {attachments.length ? (
            <div className="chat-attachments" aria-label="Pending attachments">
              {attachments.map((attachment) => (
                <PendingAttachment
                  attachment={attachment}
                  key={attachment.id}
                  onRemove={() => onRemoveAttachment?.(attachment.id)}
                />
              ))}
            </div>
          ) : null}
          {dictation.error ? (
            <div className="chat-dictation-error" role="alert">
              {dictation.error}
            </div>
          ) : null}
          <div className="chat-compose-row">
            <div className="chat-compose-leading">
              <input
                ref={fileInput}
                className="chat-file-input"
                type="file"
                multiple
                accept="image/png,image/jpeg,image/webp,image/gif,text/plain,text/markdown,text/csv,application/json,application/pdf,.docx,.xlsx,.pptx"
                onChange={(event) => {
                  if (event.target.files?.length) onFiles?.(event.target.files)
                  event.target.value = ''
                }}
              />
              <UiTooltip label="Attach images or documents">
                <button
                  aria-label="Attach images or documents"
                  className="chat-compose-tool"
                  disabled={busy}
                  onClick={() => fileInput.current?.click()}
                  type="button"
                >
                  <AbstractIcon name="plus" size={15} />
                </button>
              </UiTooltip>
            </div>
            <ComposerPrimitive.Input
              aria-label="Message Marvi"
              enterKeyHint="send"
              maxRows={9}
              onBlur={() => setFocused(false)}
              onFocus={() => setFocused(true)}
              placeholder={available ? 'Send a message…' : 'Connect a provider to chat'}
              rows={1}
            />
            <div className="chat-compose-controls">
              {onOverrideChange ? (
                <SessionModel value={override ?? {}} onChange={onOverrideChange} />
              ) : null}
              <UiTooltip
                label={
                  dictation.starting
                    ? 'Starting dictation'
                    : dictation.active
                      ? 'Stop dictation'
                      : 'Dictate message'
                }
              >
                <button
                  aria-label={
                    dictation.starting
                      ? 'Starting dictation'
                      : dictation.active
                        ? 'Stop dictation'
                        : 'Dictate message'
                  }
                  aria-pressed={dictation.active}
                  className={dictation.active ? 'chat-compose-tool active' : 'chat-compose-tool'}
                  disabled={busy || dictation.starting}
                  onClick={() => void (dictation.active ? dictation.stop() : dictation.start())}
                  type="button"
                >
                  {dictation.starting ? (
                    <GlyphSpinner ariaLabel="Starting dictation" spinner="braille" />
                  ) : (
                    <AbstractIcon name={dictation.active ? 'stop' : 'microphone'} size={15} />
                  )}
                </button>
              </UiTooltip>
              {/* While a reply is streaming the same corner stops it. A turn
                  nobody wants any more is still generating and still billed. */}
              <ThreadPrimitive.If running>
                <ComposerPrimitive.Cancel aria-label="Stop" className="chat-send is-stop">
                  <AbstractIcon name="stop" size={16} />
                </ComposerPrimitive.Cancel>
              </ThreadPrimitive.If>
              <ThreadPrimitive.If running={false}>
                <ComposerPrimitive.Send aria-label="Send" className="chat-send">
                  <AbstractIcon name="send" size={16} />
                </ComposerPrimitive.Send>
              </ThreadPrimitive.If>
            </div>
          </div>
        </div>
      </ComposerPrimitive.Root>
    </TooltipProvider>
  )
}
