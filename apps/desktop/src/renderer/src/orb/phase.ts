// Maps Marvi's assistant phases to the vendored orb states, plus the accent
// color each phase uses. The Dynamic Island reads this so the orb is driven by
// real state, not the clock.

import type { AssistantPhase } from '../../../shared/runtime'
import type { OrbState } from './types'

export const PHASE_ORB: Record<AssistantPhase, OrbState> = {
  ready: 'breathing',
  wake: 'connecting',
  listening: 'listening',
  thinking: 'searching',
  speaking: 'composing',
  // Not `composing`. Answering and volunteering should not look identical --
  // the whole point of a separate phase is that you can tell which is
  // happening from across the room, before any words arrive.
  announcing: 'weaving',
  action: 'working',
  notification: 'weaving',
  confirmation: 'solving',
  error: 'shaping'
}

export const PHASE_ACCENT: Record<AssistantPhase, string> = {
  ready: 'var(--ui-text-tertiary)',
  wake: 'var(--ui-accent)',
  listening: 'var(--ui-accent)',
  thinking: 'var(--ui-accent)',
  speaking: 'var(--ui-accent)',
  // Her own colour, used nowhere else, so an unprompted line is recognisable
  // as one at a glance.
  announcing: 'var(--ui-announce)',
  action: 'var(--ui-accent)',
  notification: 'var(--ui-accent)',
  confirmation: 'var(--ui-accent)',
  error: 'var(--ui-danger)'
}

export function orbStateFor(phase: AssistantPhase): OrbState {
  return PHASE_ORB[phase]
}

export function accentFor(phase: AssistantPhase): string {
  return PHASE_ACCENT[phase]
}
