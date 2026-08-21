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
  onCancel,
  override,
  onOverrideChange
}: {
  draft: string
  busy: boolean
  available: boolean
  onDraftChange: (next: string) => void
  onSend: () => void
  onCancel?: () => void
  override?: { provider?: string; model?: string; effort?: string }
  onOverrideChange?: (next: { provider?: string; model?: string; effort?: string }) => void
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
        {busy && onCancel ? (
          // While a reply is streaming the same control stops it. A turn
          // nobody wants any more is still being generated and still billed.
          <button aria-label="Stop" className="chat-send" onClick={onCancel} type="button">
            ■
          </button>
        ) : (
          <button
            aria-label="Send"
            className="chat-send"
            disabled={!ready}
            onClick={onSend}
            type="button"
          >
            ↑
          </button>
        )}
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
