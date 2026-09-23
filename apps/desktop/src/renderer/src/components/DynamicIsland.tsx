import { useStore } from '@nanostores/react'

import type { VoiceState } from '../store/voice-state'
import { $appearanceStyle } from '../store/appearance'
import { Orb } from '../orb/Orb'
import { accentFor, orbStateFor } from '../orb/phase'
import { announcementSourceLabel } from './island-presentation'
import { $interfaceLocale, t } from '../store/locale'

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
  const locale = useStore($interfaceLocale)
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
        aria-label={`${t('Room', locale)}: ${state.roomEvent.summary}`}
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
            <small>{t('ROOM', locale)}</small>
            <strong dir="auto">{state.roomEvent.summary}</strong>
          </div>
        ) : null}
      </div>
    )
  }

  if (state.phase === 'ready') {
    return (
      <div className="dynamic-island island-seed" data-phase="ready" role="status">
        <span className="island-seed-line" aria-hidden="true" />
        <span className="sr-only">{t('Marvi OS ready', locale)}</span>
      </div>
    )
  }

  if (state.phase === 'confirmation' && state.confirmation) {
    return (
      <div
        className="dynamic-island island-confirmation"
        data-phase="confirmation"
        role="alertdialog"
        aria-label={t('Action confirmation', locale)}
      >
        <div className="confirmation-copy">
          <small>{t('CONFIRM', locale)}</small>
          <strong dir="auto">{t(state.confirmation.action, locale)}</strong>
          <span dir="auto">{t(state.confirmation.detail, locale)}</span>
        </div>
        <div className="confirmation-actions">
          <button
            disabled={confirmationPending}
            type="button"
            onClick={() => onConfirmationDecision?.('deny')}
          >
            {t('DENY', locale)}
          </button>
          <button
            className="confirm-primary"
            disabled={confirmationPending}
            type="button"
            onClick={() => onConfirmationDecision?.('approve')}
          >
            {t(confirmationPending ? 'WAIT…' : 'APPROVE', locale)}
          </button>
        </div>
      </div>
    )
  }

  const reactive = state.phase === 'listening' || state.phase === 'speaking'
  const announcement = state.phase === 'announcing' ? state.announcement : null
  const label = announcement
    ? `${t(announcementSourceLabel(announcement.source), locale)} · ${t('NOW', locale)}`
    : t(ISLAND_PHASE_LABEL[state.phase], locale)
  const caption = announcement?.text ?? t(state.caption, locale)
  const detail = announcement ? null : state.detail ? t(state.detail, locale) : null

  return (
    <div
      aria-label={`${label}: ${caption}${detail ? `. ${detail}` : ''}`}
      className={`dynamic-island island-${state.phase} ${expanded ? 'is-expanded' : 'is-collapsed'}`}
      data-announcement-active={announcement?.active ?? undefined}
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
          <strong dir="auto">{caption}</strong>
          {detail ? <span dir="auto">{detail}</span> : null}
        </div>
      ) : (
        <small className="island-compact-label" aria-hidden="true">
          {announcement
            ? t(announcementSourceLabel(announcement.source), locale)
            : t(ISLAND_PHASE_LABEL[state.phase], locale)}
        </small>
      )}
    </div>
  )
}

const ISLAND_PHASE_LABEL: Record<VoiceState['phase'], string> = {
  ready: 'READY',
  wake: 'AWAKE',
  listening: 'LISTEN',
  thinking: 'THINK',
  speaking: 'SPEAK',
  announcing: 'MARVI',
  action: 'WORKING',
  notification: 'NOTICE',
  confirmation: 'CONFIRM',
  error: 'OFFLINE'
}
