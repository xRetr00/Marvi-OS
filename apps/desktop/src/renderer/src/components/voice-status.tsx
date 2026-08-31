/**
 * What Marvi is doing, in the page header.
 *
 * It began as a panel floating in the top-left of the field, the size of a
 * paragraph, competing with two cards and the orb for the same glance. The
 * header already had a slot for exactly this and was spending it on
 * `READY / Say Marvi` — the phase and a caption, hardcoded into the topbar,
 * saying nothing the state could not say for itself.
 *
 * So the panel moves into that slot. One row, sized to the header rather than
 * to its content: the phase word, the sentence, and — only when there is one —
 * the reason nothing is working.
 */
import type { AssistantState, ComponentStatus } from '../../../shared/runtime'

export interface VoiceStatusProps {
  voice: AssistantState
  /** Whether the session is joined. Not joined is its own state, and saying
   * READY for it was a lie: the page claimed Marvi was listening while nothing
   * was in the room. */
  link: 'idle' | 'connecting' | 'live' | string
  /** The worker is loading its speech models and cannot hear anything yet. */
  warming: boolean
  /** The one line that answers "why is nothing happening", or empty. */
  blocker?: string
  /** Whether the wake word is listening, when that is known. */
  wake?: ComponentStatus | null
}

export function VoiceStatus({
  voice,
  link,
  warming,
  blocker
}: VoiceStatusProps): React.JSX.Element {
  const phase = warming ? 'starting' : link === 'live' ? voice.phase : 'idle'
  const word = warming
    ? 'WARMING UP'
    : link === 'live'
      ? voice.phase.toUpperCase()
      : link === 'connecting'
        ? 'JOINING'
        : 'IDLE'
  const line = warming
    ? 'Loading the speech models'
    : link === 'live'
      ? voice.caption
      : 'Press Join to start listening'

  return (
    <span className="topbar-state voice-status" data-phase={phase}>
      <span className={`voice-hud-phase phase-${phase}`}>{word}</span>
      <span className="voice-status-line">{line}</span>
      {/* Only when it has something to say. A permanent empty slot in a header
          is furniture, and this one is meant to be read when it appears. */}
      {blocker ? <span className="voice-status-blocker">{blocker}</span> : null}
    </span>
  )
}
