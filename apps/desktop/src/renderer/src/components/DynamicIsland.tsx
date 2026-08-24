import type { DeviceState } from '../../../shared/runtime'
import type { VoiceState } from '../store/voice-state'
import { Orb } from '../orb/Orb'
import { accentFor, orbStateFor } from '../orb/phase'

const VOICE_ACTIVE = new Set(['wake', 'listening', 'thinking', 'speaking'])

export function DynamicIsland({
  state,
  microphone = 'unknown',
  camera = 'unknown',
  confirmationPending = false,
  onConfirmationDecision
}: {
  state: VoiceState
  /** Passed in rather than read off `state`, which used to carry two booleans
   * nothing ever set — so the island lit MIC and CAM permanently. This is the
   * one indicator a user checks to see whether they are being listened to, so
   * it defaults to unknown and only lights on evidence. */
  microphone?: DeviceState
  camera?: DeviceState
  confirmationPending?: boolean
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
        <Orb
          state={orbStateFor('ready')}
          size={20}
          accent={accentFor('ready')}
          level={state.level}
          className="island-orb"
        />
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

  if (state.phase === 'ready' && state.yolo) {
    return (
      <div className="dynamic-island island-yolo" data-phase="ready" role="status">
        <strong>⚡ YOLO</strong>
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
          <button
            disabled={confirmationPending}
            type="button"
            onClick={() => onConfirmationDecision?.('deny')}
          >
            DENY
          </button>
          <button
            className="confirm-primary"
            disabled={confirmationPending}
            type="button"
            onClick={() => onConfirmationDecision?.('approve')}
          >
            {confirmationPending ? 'WAIT…' : 'APPROVE'}
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
          <span className={microphone === 'on' ? 'signal-on' : ''}>
            MIC{microphone === 'unknown' ? '?' : ''}
          </span>
          <span className={camera === 'on' ? 'signal-on' : ''}>
            CAM{camera === 'unknown' ? '?' : ''}
          </span>
        </div>
      ) : null}
    </div>
  )
}
