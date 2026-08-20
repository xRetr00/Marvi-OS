import type { Room } from 'livekit-client'
import { atom } from 'nanostores'

import { connectVoiceRoom } from '../lib/livekit-room'
import { cycleVoicePhase } from './voice-state'

/**
 * Whether Marvi is in the room, and the two controls that decide it.
 *
 * The session used to be started once from App's mount effect with the handle
 * kept in that effect's closure, which meant there was no way to end it: the
 * only way to stop Marvi listening was to quit. An always-on assistant needs a
 * way to be off — for a meeting, for a call, for a conversation that is not
 * hers — and needs it in the obvious place rather than in a settings page.
 *
 * The room lives here rather than in component state because it must survive
 * navigating away from the voice page. Leaving the page is not hanging up.
 */
export type VoiceLink = 'off' | 'connecting' | 'live'

export const $voiceLink = atom<VoiceLink>('off')

let room: Room | null = null
/** Guards against a second start while the first is still connecting. */
let starting: Promise<void> | null = null

export async function startVoice(): Promise<void> {
  if (room || starting) return starting ?? undefined
  $voiceLink.set('connecting')
  starting = connectVoiceRoom()
    .then((connected) => {
      room = connected
      // Ending from the other side — the agent going away, the server
      // restarting — has to land in the same state as pressing End, or the
      // button would offer to stop something already stopped.
      connected.once('disconnected', () => {
        room = null
        $voiceLink.set('off')
      })
      $voiceLink.set('live')
    })
    .catch(() => {
      room = null
      $voiceLink.set('off')
      cycleVoicePhase('error')
    })
    .finally(() => {
      starting = null
    })
  return starting
}

export async function stopVoice(): Promise<void> {
  const current = room
  room = null
  $voiceLink.set('off')
  if (current) await current.disconnect()
}

export function voiceRoom(): Room | null {
  return room
}
