import type { ChatContext } from '../../../../shared/runtime'
import { compactTokens, contextPercent, contextSegments } from '../context-breakdown'

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
  const reserve = segments.find((segment) => segment.id === 'reserve')?.tokens ?? 0
  const available = segments.find((segment) => segment.id === 'available')?.tokens ?? 0
  const used = segments
    .filter((segment) => segment.id === 'prompt' || segment.id === 'cached')
    .reduce((total, segment) => total + segment.tokens, 0)

  return (
    <div className="chat-context-card">
      <header>
        <span>Context usage</span>
        <strong>
          {percent === null ? 'Usage unknown' : `${compactTokens(used)} / ${compactTokens(window)}`}
        </strong>
      </header>
      <p>
        {percent === null
          ? 'Waiting for provider usage'
          : `${compactTokens(available)} free after ${compactTokens(reserve)} reply reserve`}
      </p>
      <div
        aria-label={percent === null ? 'Context usage unknown' : `Context window ${percent}% used`}
        className="chat-context-bar"
        role="img"
      >
        {segments
          .filter((segment) => segment.tokens > 0)
          .map((segment) => (
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
              <strong>
                {compactTokens(segment.tokens)} ·{' '}
                {window ? Math.round((segment.tokens / window) * 100) : 0}%
              </strong>
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
          <dd title={route || context?.model || 'Default'}>
            {route || context?.model || 'Default'}
          </dd>
        </div>
      </dl>
    </div>
  )
}
