import type { VoiceState } from '../store/voice-state'

const BARS = [0.35, 0.68, 0.92, 0.52, 0.78, 0.42, 0.88, 0.6, 0.3]

export function DynamicIsland({
  state,
  compact = false,
  onConfirmationDecision
}: {
  state: VoiceState
  compact?: boolean
  onConfirmationDecision?: (decision: 'approve' | 'deny') => void
}): React.JSX.Element {
  const voiceActive = ['wake', 'listening', 'thinking', 'speaking'].includes(state.phase)

  // A background room event expands the seed briefly and collapses on its own.
  // It is announced politely and never becomes interactive, so it cannot pull
  // focus away from whatever the user is doing.
  if (state.phase === 'ready' && state.roomEvent && !compact) {
    return (
      <div
        className="dynamic-island island-room-event"
        data-phase="ready"
        data-event={state.roomEvent.type}
        role="status"
        aria-live="polite"
      >
        <span className="island-orb" aria-hidden="true">
          ◦
        </span>
        <div className="island-copy">
          <small>{state.yolo ? '⚡ YOLO / ROOM' : 'ROOM'}</small>
          <strong>{state.roomEvent.summary}</strong>
        </div>
      </div>
    )
  }

  if (state.phase === 'ready' && !compact && !state.yolo) {
    return (
      <div className="dynamic-island island-seed" data-phase="ready" role="status">
        <span className="island-seed-line" aria-hidden="true" />
        <span className="sr-only">Marvi OS ready</span>
      </div>
    )
  }

  if (state.phase === 'confirmation' && state.confirmation) {
    return (
      <div
        className="dynamic-island island-confirmation"
        data-phase="confirmation"
        role="alertdialog"
        aria-label="Action confirmation"
      >
        <div className="confirmation-copy">
          <small>CONFIRM</small>
          <strong>{state.confirmation.action}</strong>
          <span>{state.confirmation.detail}</span>
        </div>
        <div className="confirmation-actions">
          <button type="button" onClick={() => onConfirmationDecision?.('deny')}>
            DENY
          </button>
          <button
            className="confirm-primary"
            type="button"
            onClick={() => onConfirmationDecision?.('approve')}
          >
            APPROVE
          </button>
        </div>
      </div>
    )
  }

  return (
    <div
      className={`dynamic-island island-${state.phase} ${compact ? 'island-compact' : ''}`}
      data-phase={state.phase}
    >
      <span className="island-orb" aria-hidden="true">
        {state.phase === 'error' ? '!' : state.phase === 'action' ? '→' : 'M'}
      </span>
      <div className="island-copy">
        <small>
          {state.yolo
            ? '⚡ YOLO'
            : state.phase === 'ready'
              ? 'MARVI OS'
              : state.phase.toUpperCase()}
        </small>
        <strong>{state.caption}</strong>
        {state.detail ? <span>{state.detail}</span> : null}
      </div>
      {voiceActive ? (
        <div className="wave active" aria-hidden="true">
          {BARS.map((bar, index) => (
            <i
              key={index}
              style={{ '--bar': bar, '--delay': `${index * -72}ms` } as React.CSSProperties}
            />
          ))}
        </div>
      ) : (
        <div className="island-signals" aria-label="Local sensor state">
          <span className={state.microphone ? 'signal-on' : ''}>MIC</span>
          <span className={state.camera ? 'signal-on' : ''}>CAM</span>
        </div>
      )}
    </div>
  )
}
