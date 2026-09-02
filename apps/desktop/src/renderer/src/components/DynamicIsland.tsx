import { useStore } from '@nanostores/react'

import type { VoiceState } from '../store/voice-state'
import { $appearanceStyle } from '../store/appearance'
import { Orb } from '../orb/Orb'
import { accentFor, orbStateFor } from '../orb/phase'

export function DynamicIsland({
  state,
  expanded = true,
  confirmationPending = false,
  onConfirmationDecision
}: {
  state: VoiceState
  expanded?: boolean
  confirmationPending?: boolean
  onConfirmationDecision?: (decision: 'approve' | 'deny') => void
}): React.JSX.Element {
  const appearance = useStore($appearanceStyle)
  // A background room event expands the seed briefly and collapses on its own.
  // It is announced politely and never becomes interactive, so it cannot pull
  // focus away from whatever the user is doing.
  if (state.phase === 'ready' && state.roomEvent) {
    return (
      <div
        className={`dynamic-island island-room-event ${expanded ? 'is-expanded' : 'is-collapsed'}`}
        data-phase="ready"
        data-event={state.roomEvent.type}
        data-expanded={expanded}
        role="status"
        aria-live="polite"
        aria-label={`Room: ${state.roomEvent.summary}`}
      >
        <Orb
          state={orbStateFor('ready')}
          size={20}
          accent={accentFor('ready')}
          level={state.level}
          className="island-orb"
          themeRevision={appearance}
        />
        {expanded ? (
          <div className="island-copy">
            <small>ROOM</small>
            <strong>{state.roomEvent.summary}</strong>
          </div>
        ) : null}
      </div>
    )
  }

  if (state.phase === 'ready') {
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
  const label = ISLAND_PHASE_LABEL[state.phase]

  return (
    <div
      aria-label={`${label}: ${state.caption}${state.detail ? `. ${state.detail}` : ''}`}
      className={`dynamic-island island-${state.phase} ${expanded ? 'is-expanded' : 'is-collapsed'}`}
      data-expanded={expanded}
      data-phase={state.phase}
      role="status"
    >
      <Orb
        state={orbStateFor(state.phase)}
        size={20}
        accent={accentFor(state.phase)}
        level={state.level}
        reactive={reactive}
        className="island-orb"
        themeRevision={appearance}
      />
      {expanded ? (
        <div className="island-copy">
          <small>{label}</small>
          <strong>{state.caption}</strong>
          {state.detail ? <span>{state.detail}</span> : null}
        </div>
      ) : null}
    </div>
  )
}

const ISLAND_PHASE_LABEL: Record<VoiceState['phase'], string> = {
  ready: 'READY',
  wake: 'AWAKE',
  listening: 'LISTEN',
  thinking: 'THINK',
  speaking: 'SPEAK',
  action: 'WORKING',
  notification: 'NOTICE',
  confirmation: 'CONFIRM',
  error: 'OFFLINE'
}
