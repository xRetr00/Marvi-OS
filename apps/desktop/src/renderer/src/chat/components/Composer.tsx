import { useCallback, useEffect, useRef, useState } from 'react'

import type { ChatAttachment, ChatContext, ModelPage } from '../../../../shared/runtime'
import { AbstractIcon } from '../../components/abstract-icon'
import { TooltipProvider, UiTooltip } from '../../components/ui/tooltip'
import { Picker, type PickerOption } from '../../components/ui/picker'
import { useDictation } from '../useDictation'
import { contextPercent } from '../context-breakdown'
import { ContextBreakdown, ContextRing } from './ContextBreakdown'
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
  onOverrideChange,
  context
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
  context?: ChatContext | null
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
              <details className="chat-context-breakdown">
                <summary
                  aria-label={
                    contextPercentLabel(context) === 'unknown'
                      ? 'Show context breakdown, usage unknown'
                      : `Show context breakdown, ${contextPercentLabel(context)} percent used`
                  }
                >
                  <ContextRing context={context} />
                </summary>
                <ContextBreakdown
                  context={context}
                  pendingFiles={attachments.length}
                  route={override?.model}
                />
              </details>
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

function contextPercentLabel(context?: ChatContext | null): number | 'unknown' {
  return contextPercent(context) ?? 'unknown'
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

  useEffect(() => {
    let gone = false
    void (async () => {
      const next = await window.marvi?.getModels({})
      if (!gone) setPage(next ?? null)
    })()
    return () => {
      gone = true
    }
  }, [])

  const providers = page?.providers ?? []
  if (providers.length === 0) return null

  // Flat, because the choice is a model and the provider follows from it. Two
  // dependent dropdowns would be a step longer for the same answer, and this
  // one lives beside a text field rather than on a settings page.
  const options: PickerOption[] = [
    { value: '', label: 'Default model', detail: 'Whatever Models is set to' },
    ...providers.flatMap((provider) =>
      provider.models.map((model) => ({
        value: `${provider.provider}::${model.id}`,
        label: model.name,
        detail: `${provider.label} · ${model.id}`
      }))
    )
  ]

  const selected = value.model ? `${value.provider}::${value.model}` : ''
  const chosen = providers
    .find((provider) => provider.provider === value.provider)
    ?.models.find((model) => model.id === value.model)

  return (
    <div className="chat-session-model">
      <Picker
        className="chat-model-picker"
        options={options}
        value={selected}
        onChange={(next) => {
          if (!next) return onChange({})
          const [provider, ...rest] = next.split('::')
          // Effort is dropped with the model: a level chosen for one model
          // means nothing on another, and may not even be accepted.
          onChange({ provider, model: rest.join('::') })
        }}
        placeholder="Default model"
        searchPlaceholder="Search models…"
      />
      {chosen?.reasons ? (
        <Picker
          className="chat-effort-picker"
          options={[
            { value: '', label: 'Default effort' },
            ...chosen.efforts.map((level) => ({
              value: level,
              label: level.charAt(0).toUpperCase() + level.slice(1)
            }))
          ]}
          value={value.effort ?? ''}
          onChange={(effort) => onChange({ ...value, effort })}
          placeholder="Default effort"
        />
      ) : null}
    </div>
  )
}
