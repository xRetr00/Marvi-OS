import type { VoiceState } from '../store/voice-state'

export const ISLAND_ENTER_SECONDS = 0.32
export const ISLAND_EXIT_SECONDS = 0.13
export const ISLAND_REDUCED_MOTION_SECONDS = 0.01
export const ISLAND_AUTO_EXPAND_MS = 1800
export const ANNOUNCEMENT_GLANCE_MS = 10_000

// Reveal the silhouette from the same 34×2 indicator as idle. Clipping avoids
// stretching text or triggering native window resizes on animation frames.
export const ISLAND_LINE_CLIP = 'inset(0px calc(50% - 17px) calc(100% - 2px) round 999px)'
export const ISLAND_OPEN_CLIP = 'inset(0px 0px 0px round 22px)'

export function islandDisplayState(state: VoiceState): VoiceState {
  if (!state.announcement || (state.phase !== 'ready' && state.phase !== 'announcing')) {
    return state
  }
  return {
    ...state,
    phase: 'announcing',
    caption: state.announcement.text,
    detail: null
  }
}

export function islandHasOrb(state: VoiceState): boolean {
  if (state.phase === 'confirmation') return false
  return state.phase !== 'ready' || Boolean(state.roomEvent)
}

export function islandInteractionMode(state: VoiceState): 'passive' | 'hover' | 'interactive' {
  if (state.phase === 'confirmation' && state.confirmation) return 'interactive'
  return islandHasOrb(state) ? 'hover' : 'passive'
}

export function islandPresentationKey(state: VoiceState): string {
  if (state.phase === 'announcing' && state.announcement) {
    return `announcement:${state.announcement.id}:${state.announcement.active ? 'active' : 'held'}`
  }
  if (state.phase === 'confirmation') {
    return `confirmation:${state.confirmation?.token ?? 'empty'}`
  }
  if (state.phase === 'ready' && state.roomEvent) return `room-event:${state.roomEvent.id}`
  return state.phase
}

export function announcementSourceLabel(source: string): string {
  const normalized = source.trim().toLowerCase()
  if (!normalized || normalized === 'marvi') return 'MARVI'
  if (normalized.includes('reminder') || normalized.startsWith('schedule')) return 'REMINDER'
  if (normalized.includes('calendar')) return 'CALENDAR'
  if (normalized.includes('mail')) return 'MAIL'
  if (normalized.startsWith('room')) return 'ROOM'
  if (normalized.startsWith('vision')) return 'VISION'
  const tail = normalized.split(':').at(-1) ?? normalized
  return tail.replaceAll('_', ' ').slice(0, 14).toUpperCase()
}
