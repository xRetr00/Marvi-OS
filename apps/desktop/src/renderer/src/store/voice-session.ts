import type { Room } from 'livekit-client'
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

export async function startVoice(): Promise<void> {
  if (room || starting) return starting ?? undefined
  $voiceError.set('')
  $voiceLink.set('connecting')
  starting = connectVoiceRoom()
    .then((connected) => {
      room = connected
      void window.marvi?.setVoiceSessionActive(true)
      // Ending from the other side — the agent going away, the server
      // restarting — has to land in the same state as pressing End, or the
      // button would offer to stop something already stopped.
      connected.once('disconnected', () => {
        void window.marvi?.setVoiceSessionActive(false)
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
  void window.marvi?.setVoiceSessionActive(false)
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

/** The topic LiveKit's agents already read as a user turn. */
export const CHAT_TOPIC = 'lk.chat'

/**
 * Say something into the conversation without saying it.
 *
 * Used by the answer buttons on a question Marvi asked. Pressing one is the
 * user answering, so it goes in as the user's own turn -- the agent framework
 * reads this topic exactly as it reads speech, and it lands in the transcript
 * where the answer to a question belongs.
 *
 * The alternative was posting the answer back through the Gateway as a tool
 * result, which puts Marvi in the position of replying to something the
 * conversation never shows her being told.
 *
 * False when there is no call. A question can still be answered out loud, and
 * the caller uses this to decide whether the buttons are worth offering.
 */
export async function sayAsUser(text: string): Promise<boolean> {
  const words = text.trim()
  if (!room || !words) return false
  await room.localParticipant.sendText(words, { topic: CHAT_TOPIC })
  return true
}
