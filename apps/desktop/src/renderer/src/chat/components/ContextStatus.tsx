import type { ChatContext } from '../../../../shared/runtime'
import { compactTokens, contextPercent } from '../context-breakdown'
import { ContextBreakdown } from './ContextBreakdown'

export function ContextStatus({
  context,
  pendingFiles,
  route
}: {
  context?: ChatContext | null
  pendingFiles: number
  route?: string
}): React.JSX.Element {
  const percent = contextPercent(context)
  const filled = Math.round(((percent ?? 0) / 100) * 8)
  const bar = `${'█'.repeat(filled)}${'░'.repeat(8 - filled)}`
  const usage = context?.context_window
    ? `${compactTokens(context.input_tokens)}/${compactTokens(context.context_window)}`
    : '—'

  return (
    <details className="status-context-breakdown">
      <summary
        aria-label={
          percent === null ? 'Show context breakdown, usage unknown' : `Show context breakdown, ${percent}% used`
        }
      >
        <span>Context</span>
        <span className="status-detail">{usage}</span>
        <span aria-hidden="true" className="status-context-meter">
          [{bar}] {percent ?? '—'}%
        </span>
      </summary>
      <ContextBreakdown context={context} pendingFiles={pendingFiles} route={route} />
    </details>
  )
}
