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
  action: 'working',
  notification: 'weaving',
  confirmation: 'solving',
  error: 'shaping'
}

export const PHASE_ACCENT: Record<AssistantPhase, string> = {
  ready: '#8a9097',
  wake: '#147ec1',
  listening: '#38bdf8',
  thinking: '#147ec1',
  speaking: '#7dd3fc',
  action: '#34d399',
  notification: '#fbbf24',
  confirmation: '#fbbf24',
  error: '#f87171'
}

export function orbStateFor(phase: AssistantPhase): OrbState {
  return PHASE_ORB[phase]
}

export function accentFor(phase: AssistantPhase): string {
  return PHASE_ACCENT[phase]
}
