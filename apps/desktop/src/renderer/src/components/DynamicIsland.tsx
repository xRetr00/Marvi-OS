import type { VoiceState } from '../store/voice-state'
import { Orb } from '../orb/Orb'
import { accentFor, orbStateFor } from '../orb/phase'

const VOICE_ACTIVE = new Set(['wake', 'listening', 'thinking', 'speaking'])

export function DynamicIsland({
  state,
  onConfirmationDecision
}: {
  state: VoiceState
  onConfirmationDecision?: (decision: 'approve' | 'deny') => void
}): React.JSX.Element {
  const voiceActive = VOICE_ACTIVE.has(state.phase)

  // A background room event expands the seed briefly and collapses on its own.
  // It is announced politely and never becomes interactive, so it cannot pull
  // focus away from whatever the user is doing.
  if (state.phase === 'ready' && state.roomEvent) {
    return (
      <div
        className="dynamic-island island-room-event"
        data-phase="ready"
        data-event={state.roomEvent.type}
        role="status"
        aria-live="polite"
      >
        <Orb state={orbStateFor('ready')} size={20} accent={accentFor('ready')} level={state.level} className="island-orb" />
        <div className="island-copy">
          <small>{state.yolo ? '⚡ YOLO / ROOM' : 'ROOM'}</small>
          <strong>{state.roomEvent.summary}</strong>
        </div>
      </div>
    )
  }

  if (state.phase === 'ready' && !state.yolo) {
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

  const reactive = state.phase === 'listening' || state.phase === 'speaking'

  return (
    <div className={`dynamic-island island-${state.phase}`} data-phase={state.phase}>
      <Orb
        state={orbStateFor(state.phase)}
        size={20}
        accent={accentFor(state.phase)}
        level={state.level}
        reactive={reactive}
        className="island-orb"
      />
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
      {!voiceActive ? (
        <div className="island-signals" aria-label="Local sensor state">
          <span className={state.microphone ? 'signal-on' : ''}>MIC</span>
          <span className={state.camera ? 'signal-on' : ''}>CAM</span>
        </div>
      ) : null}
    </div>
  )
}
