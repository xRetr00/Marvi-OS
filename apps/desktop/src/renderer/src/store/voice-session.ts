import { RoomEvent, type Room } from 'livekit-client'
import { atom } from 'nanostores'

import { connectVoiceRoom, expectDisconnect } from '../lib/livekit-room'
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

/**
 * Whether the microphone is publishing.
 *
 * Separate from joining, because they are different intentions: leaving ends
 * the conversation, muting pauses your side of one. Someone who mutes to cough
 * does not want Marvi to forget what they were talking about.
 */
export const $voiceMuted = atom(false)

/**
 * Why joining failed, in the words of whatever refused.
 *
 * It used to be discarded -- `.catch(() => cycleVoicePhase('error'))` -- and
 * the page showed that phase's canned caption, "Gateway unavailable", for
 * every possible cause including a Gateway that was perfectly fine. A refused
 * microphone and an unreachable server produced identical text.
 */
export const $voiceError = atom('')

let room: Room | null = null
/** Guards against a second start while the first is still connecting. */
let starting: Promise<void> | null = null
let readAloudRoom: Room | null = null

const AGENT_STATE_ATTRIBUTE = 'lk.agent.state'
const READ_ALOUD_METHOD = 'marvi.read_aloud'
const STOP_READ_ALOUD_METHOD = 'marvi.read_aloud.stop'

async function agentIdentity(target: Room): Promise<string> {
  const current = (): string | undefined =>
    [...target.remoteParticipants.values()].find(
      (participant) => participant.attributes[AGENT_STATE_ATTRIBUTE]
    )?.identity
  const found = current()
  if (found) return found
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      target.off(RoomEvent.ParticipantConnected, joined)
      reject(new Error('The Marvi voice worker did not join the room'))
    }, 12_000)
    const joined = (): void => {
      const identity = current()
      if (!identity) return
      window.clearTimeout(timer)
      target.off(RoomEvent.ParticipantConnected, joined)
      resolve(identity)
    }
    target.on(RoomEvent.ParticipantConnected, joined)
  })
}

export async function readAloudWithMarvi(text: string): Promise<void> {
  const owned = room === null
  const target = room ?? (await connectVoiceRoom({ microphone: false }))
  if (owned) readAloudRoom = target
  try {
    const destinationIdentity = await agentIdentity(target)
    const response = await target.localParticipant.performRpc({
      destinationIdentity,
      method: READ_ALOUD_METHOD,
      payload: JSON.stringify({ text }),
      responseTimeout: 300_000
    })
    const result = JSON.parse(response) as { ok?: boolean; error?: string }
    if (!result.ok) throw new Error(result.error || 'Marvi could not read this response')
  } finally {
    if (owned) {
      readAloudRoom = null
      expectDisconnect()
      await target.disconnect()
    }
  }
}

export async function stopMarviReadAloud(): Promise<void> {
  const target = room ?? readAloudRoom
  if (!target) return
  try {
    const destinationIdentity = await agentIdentity(target)
    await target.localParticipant.performRpc({
      destinationIdentity,
      method: STOP_READ_ALOUD_METHOD,
      payload: '{}',
      responseTimeout: 5_000
    })
  } finally {
    if (!room && readAloudRoom === target) {
      readAloudRoom = null
      expectDisconnect()
      await target.disconnect()
    }
  }
}

export async function startVoice(): Promise<void> {
  if (room || starting) return starting ?? undefined
  $voiceError.set('')
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
        // A new call starts unmuted. Carrying mute across a hang-up means
        // rejoining and silently not being heard.
        $voiceMuted.set(false)
      })
      $voiceLink.set('live')
    })
    .catch((cause: unknown) => {
      room = null
      $voiceLink.set('off')
      $voiceError.set(cause instanceof Error ? cause.message : String(cause))
      cycleVoicePhase('error')
    })
    .finally(() => {
      starting = null
    })
  return starting
}

export async function stopVoice(): Promise<void> {
  // Tell the room layer this one is on purpose, so the disconnect is not
  // reported as a failure.
  expectDisconnect()
  const current = room
  room = null
  $voiceLink.set('off')
  if (current) await current.disconnect()
}

export async function setMuted(muted: boolean): Promise<void> {
  $voiceMuted.set(muted)
  // Unpublishing rather than gating locally: a muted microphone that still
  // sends audio is a promise the UI cannot keep.
  await room?.localParticipant.setMicrophoneEnabled(!muted)
}

export function voiceRoom(): Room | null {
  return room
}
