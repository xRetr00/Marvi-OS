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

import { pastedImages } from '../paste'
import { useCallback, useRef, useState } from 'react'
import {
  ComposerPrimitive,
  ThreadPrimitive,
  unstable_useComposerInput,
  unstable_useSlashCommandAdapter
} from '@assistant-ui/react'

import type { ChatAttachment } from '../../../../shared/runtime'
import { AbstractIcon } from '../../components/abstract-icon'
import { GlyphSpinner } from '../../components/ui/glyph-spinner'
import { TooltipProvider, UiTooltip } from '../../components/ui/tooltip'
import { commandArgument, SLASH_COMMANDS, slashTrigger } from '../commands'
import { MentionSuggestions } from '../components/MentionSuggestions'
import { PendingAttachment } from '../components/PendingAttachment'
import { SessionModel } from './SessionModel'
import { useDictation } from '../useDictation'
import { useStore } from '@nanostores/react'
import { $interfaceLocale, t } from '../../store/locale'
import { $runtimeState } from '../../store/voice-state'

export function Composer({
  available,
  busy,
  attachments = [],
  onFiles,
  onRemoveAttachment,
  override,
  onOverrideChange,
  threadId,
  onNewThread
}: {
  available: boolean
  busy: boolean
  attachments?: ChatAttachment[]
  onFiles?: (files: FileList | File[]) => void
  onRemoveAttachment?: (id: string) => void
  override?: { provider?: string; model?: string; effort?: string }
  onOverrideChange?: (next: { provider?: string; model?: string; effort?: string }) => void
  /** Which conversation `/compress` folds. */
  threadId?: string
  onNewThread?: () => void
}): React.JSX.Element {
  const locale = useStore($interfaceLocale)
  const lowResource = useStore($runtimeState).resources.low_resource
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
  const dictation = useDictation(appendDictation, !lowResource)
  const active = focused || busy || Boolean(composer.value.trim())
  const [said, setSaid] = useState('')

  // Each command clears the draft itself rather than leaving `/compress`
  // sitting in the field looking like something still to send.
  const run = useCallback(
    async (id: string, work: (argument: string) => Promise<string>) => {
      const argument = commandArgument(composer.value, id)
      composer.setText('')
      setSaid(await work(argument))
    },
    [composer]
  )
  const slash = unstable_useSlashCommandAdapter({
    commands: SLASH_COMMANDS.map((command) => ({
      id: command.id,
      label: `/${command.id}${command.argument ? ` ${command.argument}` : ''}`,
      description: command.description,
      execute: () => {
        if (command.id === 'new') {
          void run(command.id, async () => {
            onNewThread?.()
            return ''
          })
        } else if (command.id === 'compress') {
          void run(command.id, async () => {
            const done = await window.marvi?.compactThread(threadId ?? 'default')
            if (!done) return 'The Gateway could not fold this conversation.'
            return done.folded
              ? 'Folded what had scrolled out into the summary.'
              : 'Nothing has scrolled out of the window yet.'
          })
        } else {
          void run(command.id, async (argument) => {
            if (!argument) return 'A goal needs words: /goal and then what the job is.'
            const card = await window.marvi?.addJob({ title: argument, assignee: 'owner' })
            return card ? `On the board: ${card.title}` : 'The Gateway would not take that card.'
          })
        }
      }
    }))
  })

  return (
    <TooltipProvider>
      <ComposerPrimitive.Unstable_TriggerPopoverRoot>
        <ComposerPrimitive.Root
          className="chat-compose"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault()
            if (event.dataTransfer.files.length) onFiles?.(event.dataTransfer.files)
          }}
          onPaste={(event) => {
            const images = pastedImages(Array.from(event.clipboardData?.files ?? []))
            if (!images.length) return
            event.preventDefault()
            onFiles?.(images)
          }}
        >
          <ComposerPrimitive.Unstable_TriggerPopover
            adapter={slash.adapter}
            aria-label={t('Commands')}
            char="/"
            className="chat-slash"
            matcher={slashTrigger}
          >
            <ComposerPrimitive.Unstable_TriggerPopover.Action {...slash.action} />
            <ComposerPrimitive.Unstable_TriggerPopoverItems>
              {(items) =>
                items.map((item, index) => (
                  <ComposerPrimitive.Unstable_TriggerPopoverItem
                    index={index}
                    item={item}
                    key={item.id}
                  >
                    <span className="chat-slash-name">{item.label}</span>
                    <span className="chat-slash-what">{item.description}</span>
                  </ComposerPrimitive.Unstable_TriggerPopoverItem>
                ))
              }
            </ComposerPrimitive.Unstable_TriggerPopoverItems>
          </ComposerPrimitive.Unstable_TriggerPopover>
          {said ? (
            <p className="chat-slash-said" role="status">
              {said}
            </p>
          ) : null}
          <MentionSuggestions
            active={focused}
            onPick={(next) => composer.setText(next)}
            text={composer.value}
          />
          <div className="chat-compose-field" data-active={active ? 'true' : 'false'}>
            {attachments.length ? (
              <div className="chat-attachments" aria-label={t('Pending attachments')}>
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
                <UiTooltip label={t('Attach images or documents', locale)}>
                  <button
                    aria-label={t('Attach images or documents', locale)}
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
                aria-label={t('Message Marvi', locale)}
                dir="auto"
                enterKeyHint="send"
                maxRows={9}
                onBlur={() => setFocused(false)}
                onFocus={() => setFocused(true)}
                placeholder={t(
                  available ? 'Send a message…' : 'Connect a provider to chat',
                  locale
                )}
                rows={1}
              />
              <div className="chat-compose-controls">
                {onOverrideChange ? (
                  <SessionModel value={override ?? {}} onChange={onOverrideChange} />
                ) : null}
                <UiTooltip
                  label={
                    lowResource
                      ? 'Voice not working in low-resource mode'
                      : dictation.starting
                      ? 'Starting dictation'
                      : dictation.active
                        ? 'Stop dictation'
                        : 'Dictate message'
                  }
                >
                  <button
                    aria-label={
                      lowResource
                        ? 'Voice not working in low-resource mode'
                        : dictation.starting
                        ? 'Starting dictation'
                        : dictation.active
                          ? 'Stop dictation'
                          : 'Dictate message'
                    }
                    aria-pressed={dictation.active}
                    className={dictation.active ? 'chat-compose-tool active' : 'chat-compose-tool'}
                    disabled={busy || dictation.starting || lowResource}
                    onClick={() => void (dictation.active ? dictation.stop() : dictation.start())}
                    type="button"
                  >
                    {dictation.starting ? (
                      <GlyphSpinner ariaLabel="Starting dictation" />
                    ) : (
                      <AbstractIcon name={dictation.active ? 'stop' : 'microphone'} size={15} />
                    )}
                  </button>
                </UiTooltip>
                {/* While a reply is streaming the same corner stops it. A turn
                  nobody wants any more is still generating and still billed. */}
                <ThreadPrimitive.If running>
                  <ComposerPrimitive.Cancel
                    aria-label={t('Stop', locale)}
                    className="chat-send is-stop"
                  >
                    <AbstractIcon name="stop" size={16} />
                  </ComposerPrimitive.Cancel>
                </ThreadPrimitive.If>
                <ThreadPrimitive.If running={false}>
                  <ComposerPrimitive.Send aria-label={t('Send', locale)} className="chat-send">
                    <AbstractIcon name="send" size={16} />
                  </ComposerPrimitive.Send>
                </ThreadPrimitive.If>
              </div>
            </div>
          </div>
        </ComposerPrimitive.Root>
      </ComposerPrimitive.Unstable_TriggerPopoverRoot>
    </TooltipProvider>
  )
}
