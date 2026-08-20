import { useEffect, useRef, useState } from 'react'

import type { ModelPage } from '../../../../shared/runtime'
import { Picker, type PickerOption } from '../../components/ui/picker'

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
  override,
  onOverrideChange
}: {
  draft: string
  busy: boolean
  available: boolean
  onDraftChange: (next: string) => void
  onSend: () => void
  override?: { provider?: string; model?: string }
  onOverrideChange?: (next: { provider?: string; model?: string }) => void
}): React.JSX.Element {
  const field = useRef<HTMLTextAreaElement | null>(null)

  // Auto-grow up to a ceiling, then scroll internally.
  useEffect(() => {
    const el = field.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`
  }, [draft])

  const ready = !busy && Boolean(draft.trim()) && available

  return (
    <div className="chat-compose">
      <div className="chat-compose-field">
        <textarea
          ref={field}
          rows={1}
          value={draft}
          placeholder={available ? 'Ask Marvi something…' : 'Connect a provider to chat'}
          disabled={busy || !available}
          aria-label="Message Marvi"
          onChange={(event) => onDraftChange(event.target.value)}
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
        <button
          aria-label="Send"
          className="chat-send"
          disabled={!ready}
          onClick={onSend}
          type="button"
        >
          {busy ? '…' : '↑'}
        </button>
      </div>
      <div className="chat-compose-foot">
        <span className="chat-compose-hint">Enter sends · Shift+Enter for a new line</span>
        {onOverrideChange ? (
          <SessionModel value={override ?? {}} onChange={onOverrideChange} />
        ) : null}
      </div>
    </div>
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
  value: { provider?: string; model?: string }
  onChange: (next: { provider?: string; model?: string }) => void
}): React.JSX.Element | null {
  const [page, setPage] = useState<ModelPage | null>(null)

  useEffect(() => {
    let disposed = false
    void (async () => {
      const next = await window.marvi?.getModels()
      if (!disposed) setPage(next ?? null)
    })()
    return () => {
      disposed = true
    }
  }, [])

  const providers = page?.providers ?? []
  if (providers.length === 0) return null

  // Flat, because the choice is a model and the provider is a consequence of
  // it. Two dependent dropdowns would be a step longer for the same answer.
  const options: PickerOption[] = [
    { value: '', label: 'Default model', detail: 'Whatever Providers is set to' },
    ...providers.flatMap((provider) =>
      provider.models.map((model) => ({
        value: `${provider.provider}::${model.id}`,
        label: model.name,
        detail: `${provider.label} · ${model.id}`
      }))
    )
  ]

  const selected = value.model ? `${value.provider}::${value.model}` : ''

  return (
    <Picker
      className="chat-model-picker"
      options={options}
      value={selected}
      onChange={(next) => {
        if (!next) return onChange({})
        const [provider, ...rest] = next.split('::')
        onChange({ provider, model: rest.join('::') })
      }}
      placeholder="Default model"
      searchPlaceholder="Search models…"
    />
  )
}
