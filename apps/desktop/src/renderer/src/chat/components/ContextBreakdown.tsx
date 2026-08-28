import type { ChatContext } from '../../../../shared/runtime'

export interface ContextSegment {
  id: 'prompt' | 'cached' | 'reserve' | 'available'
  label: string
  tokens: number
}

export function contextPercent(context?: ChatContext | null): number | null {
  if (!context?.context_window || !context.input_tokens) return null
  return Math.min(100, Math.round((context.input_tokens / context.context_window) * 100))
}

export function contextSegments(context?: ChatContext | null): ContextSegment[] {
  if (!context?.context_window || !context.input_tokens) return []

  const window = context.context_window
  const used = Math.min(window, Math.max(0, context.input_tokens))
  const cached = Math.min(used, Math.max(0, context.cached_tokens))
  const prompt = Math.max(0, used - cached)
  const reserve = Math.min(Math.max(0, window - used), Math.max(0, context.reply_reserve))
  const available = Math.max(0, window - used - reserve)

  return [
    { id: 'prompt', label: 'Prompt', tokens: prompt },
    { id: 'cached', label: 'Cached', tokens: cached },
    { id: 'reserve', label: 'Reply reserve', tokens: reserve },
    { id: 'available', label: 'Available', tokens: available }
  ]
}

export function ContextRing({ context }: { context?: ChatContext | null }): React.JSX.Element {
  const percent = contextPercent(context)
  return (
    <span
      aria-hidden="true"
      className="chat-context-ring"
      style={{ '--context-fill': `${(percent ?? 0) * 3.6}deg` } as React.CSSProperties}
    >
      {percent ?? '—'}
    </span>
  )
}

export function ContextBreakdown({
  context,
  pendingFiles,
  route
}: {
  context?: ChatContext | null
  pendingFiles: number
  route?: string
}): React.JSX.Element {
  const percent = contextPercent(context)
  const segments = contextSegments(context)
  const window = context?.context_window ?? 0

  return (
    <div className="chat-context-card">
      <header>
        <span>Context usage</span>
        <strong>
          {percent === null
            ? 'Usage unknown'
            : `${compactTokens(context?.input_tokens ?? 0)} / ${compactTokens(window)}`}
        </strong>
      </header>
      <p>{percent === null ? 'Waiting for provider usage' : `${percent}% of the window used`}</p>
      <div
        aria-label={percent === null ? 'Context usage unknown' : `Context window ${percent}% used`}
        className="chat-context-bar"
        role="img"
      >
        {segments.map((segment) => (
          <span
            className={`is-${segment.id}`}
            key={segment.id}
            style={{ width: `${window ? (segment.tokens / window) * 100 : 0}%` }}
          />
        ))}
      </div>
      {segments.length ? (
        <ul className="chat-context-segments">
          {segments.map((segment) => (
            <li key={segment.id}>
              <span>
                <i className={`is-${segment.id}`} />
                {segment.label}
              </span>
              <strong>{compactTokens(segment.tokens)}</strong>
            </li>
          ))}
        </ul>
      ) : null}
      <dl>
        <div>
          <dt>MESSAGES</dt>
          <dd>{context?.messages ?? 0}</dd>
        </div>
        <div>
          <dt>FILES</dt>
          <dd>{(context?.files ?? 0) + pendingFiles}</dd>
        </div>
        <div>
          <dt>SOURCES</dt>
          <dd>{context?.sources ?? 0}</dd>
        </div>
        <div>
          <dt>ROUTE</dt>
          <dd title={route || context?.model || 'Default'}>{route || context?.model || 'Default'}</dd>
        </div>
      </dl>
    </div>
  )
}

function compactTokens(value: number): string {
  if (value >= 1_000_000) {
    const scaled = value / 1_000_000
    return `${scaled.toFixed(scaled >= 10 || Number.isInteger(scaled) ? 0 : 1)}m`
  }
  if (value >= 1_000) {
    const scaled = value / 1_000
    return `${scaled.toFixed(scaled >= 10 || Number.isInteger(scaled) ? 0 : 1)}k`
  }
  return value.toLocaleString()
}
