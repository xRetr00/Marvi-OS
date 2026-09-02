import type { VoiceState } from '../store/voice-state'

export const ISLAND_ENTER_SECONDS = 0.2
export const ISLAND_EXIT_SECONDS = 0.13
export const ISLAND_REDUCED_MOTION_SECONDS = 0.01
export const ISLAND_AUTO_EXPAND_MS = 1800

export function islandHasOrb(state: VoiceState): boolean {
  if (state.phase === 'confirmation') return false
  return state.phase !== 'ready' || Boolean(state.roomEvent)
}

export function islandInteractionMode(
  state: VoiceState
): 'passive' | 'hover' | 'interactive' {
  if (state.phase === 'confirmation' && state.confirmation) return 'interactive'
  return islandHasOrb(state) ? 'hover' : 'passive'
}

export function islandPresentationKey(state: VoiceState): string {
  if (state.phase === 'confirmation') {
    return `confirmation:${state.confirmation?.token ?? 'empty'}`
  }
  if (state.phase === 'ready' && state.roomEvent) return `room-event:${state.roomEvent.id}`
  return state.phase
}
