import { useStore } from '@nanostores/react'

import { haptic } from '../lib/haptics'
import {
  $voiceError,
  $voiceLink,
  $voiceMuted,
  setMuted,
  startVoice,
  stopVoice
} from '../store/voice-session'

/**
 * The call controls: join, mute, hang up.
 *
 * Replaces a bare START/END word sitting on the orb. Being in the room is a
 * call, so it gets the controls a call has — and the level meter is part of
 * that, because "is it hearing me" is the question you actually have when
 * nothing seems to be happening.
 *
 * It sits in its own bar rather than floating over the orb because the orb
 * surface takes the pointer for rotation, and controls that share a surface
 * with a drag target are controls you fight with.
 */
export function ConversationBar({ level }: { level: number }): React.JSX.Element {
  const link = useStore($voiceLink)
  const muted = useStore($voiceMuted)
  const failure = useStore($voiceError)
  const live = link === 'live'
  const joining = link === 'connecting'

  return (
    <div className="convo-bar">
      <div className="convo-meter" aria-hidden="true">
        {/* Twelve bars, lit from the middle out. Static when not in a call:
            an idle meter that still animates says Marvi is listening when it
            is not. */}
        {Array.from({ length: 12 }, (_, index) => {
          const distance = Math.abs(index - 5.5) / 5.5
          const lit = live && !muted && level > distance * 0.9
          return (
            <span
              key={index}
              className={`convo-bar-tick${lit ? ' is-lit' : ''}`}
              style={lit ? { transform: `scaleY(${0.35 + level * (1 - distance)})` } : undefined}
            />
          )
        })}
      </div>

      <span className={`convo-state${failure ? ' is-failed' : ''}`}>
        {/* The actual reason, not a phase caption. "Gateway unavailable" was
            shown for a refused microphone on a healthy Gateway. */}
        {failure || (live ? 'In the room' : joining ? 'Joining…' : 'Not joined')}
      </span>

      <button
        type="button"
        className={`convo-button${muted ? ' is-muted' : ''}`}
        disabled={!live}
        aria-pressed={muted}
        aria-label={muted ? 'Unmute the microphone' : 'Mute the microphone'}
        onClick={() => {
          haptic('tap')
          void setMuted(!muted)
        }}
      >
        {muted ? 'Unmute' : 'Mute'}
      </button>

      <button
        type="button"
        className={`convo-button convo-call${live || joining ? ' is-live' : ''}`}
        disabled={joining}
        aria-label={live ? 'Leave the room' : 'Join the room'}
        onClick={() => {
          haptic('tap')
          void (live ? stopVoice() : startVoice())
        }}
      >
        {live || joining ? 'Leave' : 'Join'}
      </button>
    </div>
  )
}
