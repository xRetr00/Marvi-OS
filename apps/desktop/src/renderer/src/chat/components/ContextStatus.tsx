import type { ChatContext } from '../../../../shared/runtime'
import {
  compactTokens,
  contextMeterCells,
  contextPercent,
  contextSegments
} from '../context-breakdown'
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
  const cells = contextMeterCells(context)
  const used = contextSegments(context)
    .filter((segment) => segment.id === 'prompt' || segment.id === 'cached')
    .reduce((total, segment) => total + segment.tokens, 0)
  const usage = context?.context_window
    ? `${compactTokens(used)}/${compactTokens(context.context_window)}`
    : '—'

  return (
    <details className="status-context-breakdown">
      <summary
        aria-label={
          percent === null
            ? 'Show context breakdown, usage unknown'
            : `Show context breakdown, ${percent}% used`
        }
      >
        <span className="status-context-label">Context</span>
        <span className="status-detail">{usage}</span>
        <span aria-hidden="true" className="status-context-meter">
          {cells.map((cell, index) => (
            <i className={`is-${cell}`} key={index} />
          ))}
        </span>
        <span className="status-context-percent">{percent ?? '—'}%</span>
      </summary>
      <ContextBreakdown context={context} pendingFiles={pendingFiles} route={route} />
    </details>
  )
}
