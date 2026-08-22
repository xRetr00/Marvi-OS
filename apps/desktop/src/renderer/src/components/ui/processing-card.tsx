import { AbstractIcon, type AbstractIconName } from '../abstract-icon'

export interface ProcessingStage {
  label: string
  state: 'waiting' | 'active' | 'complete' | 'error'
}

export function ProcessingCard({
  title,
  detail,
  icon = 'activity',
  progress,
  stages = [],
  compact = false
}: {
  title: string
  detail: string
  icon?: AbstractIconName
  progress?: number
  stages?: readonly ProcessingStage[]
  compact?: boolean
}): React.JSX.Element {
  const determinate = Number.isFinite(progress)
  const value = determinate ? Math.max(0, Math.min(100, Number(progress))) : undefined
  return (
    <section
      aria-busy="true"
      aria-label={title}
      className={`processing-card${compact ? ' processing-card-compact' : ''}`}
    >
      <div className="processing-visual" aria-hidden="true">
        <span className="processing-scan" />
        <span className="processing-glyph">{'┌─┐\n│◆│\n└─┘'}</span>
      </div>
      <div className="processing-copy">
        <span className="processing-kicker">
          <AbstractIcon name={icon} size={15} /> PROCESSING
        </span>
        <strong>{title}</strong>
        <small>{detail}</small>
        <div
          aria-label={determinate ? `${Math.round(value ?? 0)} percent` : 'In progress'}
          aria-valuemax={determinate ? 100 : undefined}
          aria-valuemin={determinate ? 0 : undefined}
          aria-valuenow={determinate ? value : undefined}
          className={`processing-track${determinate ? '' : ' indeterminate'}`}
          role="progressbar"
        >
          <span style={determinate ? { width: `${value}%` } : undefined} />
        </div>
        {stages.length > 0 ? (
          <div className="processing-stages">
            {stages.map((stage) => (
              <span className={`processing-stage stage-${stage.state}`} key={stage.label}>
                {stage.state === 'complete' ? '✓' : stage.state === 'error' ? '!' : '·'}{' '}
                {stage.label}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  )
}
