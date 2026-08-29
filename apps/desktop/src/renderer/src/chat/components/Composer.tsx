import { useCallback, useEffect, useRef, useState } from 'react'

import type { ChatAttachment, ModelPage, ProviderPage } from '../../../../shared/runtime'
import { AbstractIcon } from '../../components/abstract-icon'
import { TooltipProvider, UiTooltip } from '../../components/ui/tooltip'
import { ModelPicker } from '../../components/ui/model-picker'
import { useDictation } from '../useDictation'
import { PendingAttachment } from './PendingAttachment'

/**
 * One field with its send control inside it.
 *
 * It used to be a textarea with two full-width buttons stacked underneath, so
 * the two loudest things on the page were CLEAR and SEND. Clear moved to the
 * header where a destructive action belongs, and send became a small control
 * on the edge of the field it submits — which is also where the keyboard
 * shortcut already sent it.
 */
export function Composer({
  draft,
  busy,
  available,
  onDraftChange,
  onSend,
  onCancel,
  attachments = [],
  onFiles,
  onRemoveAttachment,
  override,
  onOverrideChange
}: {
  draft: string
  busy: boolean
  available: boolean
  onDraftChange: (next: string) => void
  onSend: () => void
  onCancel?: () => void
  attachments?: ChatAttachment[]
  onFiles?: (files: FileList | File[]) => void
  onRemoveAttachment?: (id: string) => void
  override?: { provider?: string; model?: string; effort?: string }
  onOverrideChange?: (next: { provider?: string; model?: string; effort?: string }) => void
}): React.JSX.Element {
  const field = useRef<HTMLTextAreaElement | null>(null)
  const fileInput = useRef<HTMLInputElement | null>(null)
  const [focused, setFocused] = useState(false)
  const appendDictation = useCallback(
    (text: string) => onDraftChange(`${draft}${draft.trim() ? ' ' : ''}${text}`),
    [draft, onDraftChange]
  )
  const dictation = useDictation(appendDictation)

  // Auto-grow up to a ceiling, then scroll internally.
  useEffect(() => {
    const el = field.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`
  }, [draft])

  const ready = !busy && Boolean(draft.trim()) && available
  return (
    <TooltipProvider>
      <div
        className="chat-compose"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault()
          if (event.dataTransfer.files.length) onFiles?.(event.dataTransfer.files)
        }}
      >
        <div
          className="chat-compose-field"
          data-active={focused || busy || Boolean(draft.trim()) ? 'true' : 'false'}
        >
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
            <textarea
              ref={field}
              rows={1}
              value={draft}
              placeholder={available ? 'Send a message…' : 'Connect a provider to chat'}
              disabled={!available}
              aria-label="Message Marvi"
              enterKeyHint="send"
              onBlur={() => setFocused(false)}
              onChange={(event) => onDraftChange(event.target.value)}
              onFocus={() => setFocused(true)}
              onKeyDown={(event) => {
                // Enter sends, Shift+Enter breaks the line, Ctrl/Cmd+Enter always sends.
                const wantsSend =
                  event.key === 'Enter' && (!event.shiftKey || event.ctrlKey || event.metaKey)
                if (wantsSend) {
                  event.preventDefault()
                  onSend()
                }
              }}
            />
            <div className="chat-compose-controls">
              {onOverrideChange ? (
                <SessionModel value={override ?? {}} onChange={onOverrideChange} />
              ) : null}
              <UiTooltip label={dictation.active ? 'Stop dictation' : 'Dictate message'}>
                <button
                  aria-label={dictation.active ? 'Stop dictation' : 'Dictate message'}
                  aria-pressed={dictation.active}
                  className={dictation.active ? 'chat-compose-tool active' : 'chat-compose-tool'}
                  disabled={busy || dictation.starting}
                  onClick={() => void (dictation.active ? dictation.stop() : dictation.start())}
                  type="button"
                >
                  <AbstractIcon name={dictation.active ? 'stop' : 'microphone'} size={15} />
                </button>
              </UiTooltip>
              {busy && onCancel ? (
                // While a reply is streaming the same control stops it. A turn
                // nobody wants any more is still being generated and still billed.
                <button
                  aria-label="Stop"
                  className="chat-send is-stop"
                  onClick={onCancel}
                  type="button"
                >
                  <AbstractIcon name="stop" size={16} />
                </button>
              ) : (
                <button
                  aria-label="Send"
                  className="chat-send"
                  disabled={!ready}
                  onClick={onSend}
                  type="button"
                >
                  <AbstractIcon name="send" size={16} />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </TooltipProvider>
  )
}

/**
 * The model for this conversation, and only this one.
 *
 * It overrides the configured default for the turns you send from here and is
 * stored nowhere — close the window and it is gone. That is deliberate: trying
 * a model on one conversation should not silently become the model voice, mind
 * and vision use too.
 */
function SessionModel({
  value,
  onChange
}: {
  value: { provider?: string; model?: string; effort?: string }
  onChange: (next: { provider?: string; model?: string; effort?: string }) => void
}): React.JSX.Element | null {
  const [page, setPage] = useState<ModelPage | null>(null)
  const [settings, setSettings] = useState<ProviderPage | null>(null)

  useEffect(() => {
    let gone = false
    void (async () => {
      const [next, providers] = await Promise.all([
        window.marvi?.getModels({}),
        window.marvi?.getProviders()
      ])
      if (!gone) {
        setPage(next ?? null)
        setSettings(providers ?? null)
      }
    })()
    return () => {
      gone = true
    }
  }, [])

  const providers = page?.providers ?? []
  if (providers.length === 0) return null
  const defaultProvider = providers.find((provider) => provider.provider === settings?.selected)
  const defaultModel = defaultProvider?.models.find(
    (model) => model.id === defaultProvider.selected
  )
  const defaultSelection =
    defaultProvider?.provider && defaultProvider.selected
      ? { provider: defaultProvider.provider, model: defaultProvider.selected }
      : undefined
  const defaultDetail = defaultProvider
    ? `${defaultModel?.name ?? defaultProvider.selected} · ${defaultProvider.label}`
    : 'Uses the Models setting'

  return (
    <div className="chat-session-model">
      <ModelPicker
        className="chat-model-picker"
        defaultOption={{
          label: 'Default model',
          detail: defaultDetail,
          selection: defaultSelection
        }}
        effort={value.effort ?? ''}
        effortDefaultLabel="Default effort"
        providers={providers}
        side="top"
        value={
          value.model && value.provider ? { provider: value.provider, model: value.model } : null
        }
        onChange={(next, options) => {
          if (!next) return onChange({})
          if (options) return onChange({ ...next, effort: options.effort })
          // Effort is dropped with the model: a level chosen for one model
          // means nothing on another, and may not even be accepted.
          onChange(next)
        }}
        placeholder="Default model"
        searchPlaceholder="Search models…"
      />
    </div>
  )
}
