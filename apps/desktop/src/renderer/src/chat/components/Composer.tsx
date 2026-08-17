import { useEffect, useRef } from 'react'

export function Composer({
  draft,
  busy,
  available,
  canClear,
  onDraftChange,
  onSend,
  onClear
}: {
  draft: string
  busy: boolean
  available: boolean
  canClear: boolean
  onDraftChange: (next: string) => void
  onSend: () => void
  onClear: () => void
}): React.JSX.Element {
  const field = useRef<HTMLTextAreaElement | null>(null)

  // Auto-grow up to a ceiling, then scroll internally.
  useEffect(() => {
    const el = field.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [draft])

  return (
    <div className="chat-compose">
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
      <div className="chat-compose-actions">
        <button className="phase" type="button" disabled={busy || !canClear} onClick={onClear}>
          CLEAR
        </button>
        <button
          className="phase active"
          type="button"
          disabled={busy || !draft.trim() || !available}
          onClick={onSend}
        >
          {busy ? 'SENDING…' : 'SEND'}
        </button>
      </div>
    </div>
  )
}
