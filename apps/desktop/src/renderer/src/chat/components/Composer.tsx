import { useEffect, useRef } from 'react'

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
  onSend
}: {
  draft: string
  busy: boolean
  available: boolean
  onDraftChange: (next: string) => void
  onSend: () => void
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
      <span className="chat-compose-hint">Enter sends · Shift+Enter for a new line</span>
    </div>
  )
}
