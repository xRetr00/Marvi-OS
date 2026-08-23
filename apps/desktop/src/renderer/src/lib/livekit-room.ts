import {
  ConnectionState,
  RemoteParticipant,
  Room,
  RoomEvent,
  Track,
  createAudioAnalyser,
  type LocalAudioTrack,
  type RemoteTrack
} from 'livekit-client'

import {
  ATTR_FINAL,
  ATTR_SEGMENT,
  TRANSCRIPTION_TOPIC,
  applyTranscript,
  clearTranscript
} from '../store/transcript'
import { $voiceState, cycleVoicePhase, setVoiceLevel } from '../store/voice-state'

interface LiveKitConnection {
  url: string
  room: string
  token: string
}

const AGENT_STATE_ATTRIBUTE = 'lk.agent.state'

/** Long enough for a cold worker to warm; short enough to still be an answer. */
const AGENT_JOIN_GRACE_MS = 12_000

function publishPhase(phase: Parameters<typeof cycleVoicePhase>[0]): void {
  cycleVoicePhase(phase)
  window.marvi.publishVoiceState($voiceState.get())
}

function applyAgentState(participant: RemoteParticipant): void {
  const state = participant.attributes[AGENT_STATE_ATTRIBUTE]
  if (state === 'listening') publishPhase('listening')
  else if (state === 'thinking') publishPhase('thinking')
  else if (state === 'speaking') publishPhase('speaking')
  else if (state === 'initializing') publishPhase('wake')
  else if (state) publishPhase('ready')
}

/**
 * Stream the local mic level into the voice store so the orbs breathe with
 * real energy rather than a clock. Runs for the life of the room.
 */
function streamMicLevel(track: LocalAudioTrack): () => void {
  const analyser = createAudioAnalyser(track, {
    cloneTrack: true,
    smoothingTimeConstant: 0.8
  })
  const timer = window.setInterval(() => {
    setVoiceLevel(analyser.calculateVolume())
  }, 100)
  return () => window.clearInterval(timer)
}

/** Wait for the Gateway, without asking it for anything expensive.
 *
 * `getVoiceSession()` mints a JWT with a fresh participant identity. Retrying
 * *that* thirty times while the Gateway starts produced thirty tokens and
 * thirty identities, all but one thrown away — 58 of them in one session of
 * the log. Readiness is a cheap question; the token is not, so the cheap one
 * is asked first.
 */
/** A message worth showing, from whatever was thrown. */
function describe(cause: unknown): string {
  if (cause instanceof Error) {
    // DOMException carries the useful part in `name` -- NotAllowedError for a
    // refused microphone, NotFoundError for no device at all.
    return cause.name && cause.name !== 'Error' ? `${cause.name}: ${cause.message}` : cause.message
  }
  return String(cause)
}

async function waitForGateway(attempts = 30): Promise<void> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const runtime = await window.marvi?.getRuntime()
      if (runtime?.components?.gateway?.state === 'ready') return
    } catch {
      // Not up yet. The wait below is the whole handling.
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1_000))
  }
  throw new Error('Marvi Gateway did not become ready')
}

/**
 * What the browser does to the microphone before the recogniser hears it.
 *
 * Echo cancellation stays on always: without it Marvi's own voice comes back
 * through the microphone, and the VAD reads that as you interrupting her.
 *
 * The other two are a real trade and they default off now. Noise suppression
 * and automatic gain are tuned for a human listener -- they remove what sounds
 * like noise and even out what sounds too quiet, and both throw away the
 * phonetic detail a recogniser is using. A model that benchmarks at 6.9% word
 * error rate on clean audio does not turn "any tool" into "any too cool" on its
 * own; the audio reaching it has usually been processed first.
 *
 * Kept as switches rather than a decision, because the right answer depends on
 * the room: a noisy one may well want them back.
 */
function micProcessing(): {
  echoCancellation: boolean
  noiseSuppression: boolean
  autoGainControl: boolean
  channelCount: number
} {
  const on = (key: string, fallback: boolean): boolean => {
    const raw = window.localStorage?.getItem(key)
    return raw === null || raw === undefined ? fallback : raw === 'true'
  }
  return {
    echoCancellation: true,
    noiseSuppression: on('marvi.mic.noiseSuppression', false),
    autoGainControl: on('marvi.mic.autoGainControl', false),
    channelCount: 1
  }
}

/** Set while `stopVoice` is hanging up, so the disconnect is not an error. */
let deliberate = false

export function expectDisconnect(): void {
  deliberate = true
}

export async function connectVoiceRoom(options: { microphone?: boolean } = {}): Promise<Room> {
  deliberate = false
  await waitForGateway()

  // One token, now that there is something to give it to. Two attempts rather
  // than one because the Gateway can answer /runtime a moment before it can
  // issue a token, and a second try costs one JWT instead of thirty.
  // The IPC handler answers `null` on any failure rather than throwing, so
  // catching was never enough: a null broke out of the loop on the first pass
  // and the retry never happened. Retry on a falsy answer too.
  let connection: LiveKitConnection | undefined | null
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      connection = await window.marvi.getVoiceSession()
      if (connection) break
    } catch {
      // Fall through to the wait; the message below is the reported reason.
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1_000))
  }
  if (!connection) {
    throw new Error('The Gateway would not issue a voice token for this room')
  }
  const room = new Room({
    adaptiveStream: true,
    dynacast: true,
    audioCaptureDefaults: micProcessing()
  })
  room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
    if (track.kind === Track.Kind.Audio) track.attach()
  })
  room.on(RoomEvent.ParticipantAttributesChanged, (_changed, participant) => {
    if (participant instanceof RemoteParticipant) applyAgentState(participant)
  })
  room.on(RoomEvent.ParticipantConnected, applyAgentState)
  room.on(RoomEvent.ParticipantDisconnected, (participant: RemoteParticipant) => {
    // The agent left, so the conversation is over -- leave with it.
    //
    // `end_conversation` closed the agent's session and ended its job, and
    // nothing told this side. The room stayed connected with the microphone
    // live, and the last agent state ever published was `listening`, so the
    // page went on saying Listening to somebody who had gone. You could talk
    // into it indefinitely.
    if (!participant.attributes?.[AGENT_STATE_ATTRIBUTE]) return
    expectDisconnect()
    void room.disconnect()
  })
  room.on(RoomEvent.Disconnected, () => {
    // Not an error by itself. Leaving is a disconnect, and publishing the
    // error phase for one made pressing Leave display "Gateway unavailable" --
    // the canned caption for that phase, on a Gateway that was fine.
    publishPhase(deliberate ? 'ready' : 'error')
  })
  room.on(RoomEvent.Reconnecting, () => publishPhase('wake'))
  room.on(RoomEvent.Reconnected, () => publishPhase('ready'))
  try {
    await room.connect(connection.url, connection.token, { autoSubscribe: true })
  } catch (cause) {
    throw new Error(`Could not join the room at ${connection.url}: ${describe(cause)}`)
  }

  // Named separately from the connect: this is the step that asks the
  // operating system for the microphone, and "could not join" for a refused
  // permission sends you looking in entirely the wrong place.
  if (options.microphone !== false) {
    try {
      await room.localParticipant.setMicrophoneEnabled(true, micProcessing())
    } catch (cause) {
      await room.disconnect()
      throw new Error(`The microphone could not be opened: ${describe(cause)}`)
    }
  }

  const micTrack = room.localParticipant.getTrackPublication(Track.Source.Microphone)
    ?.audioTrack as LocalAudioTrack | undefined
  let stopLevel: (() => void) | undefined
  if (micTrack) stopLevel = streamMicLevel(micTrack)
  room.on(RoomEvent.Disconnected, () => stopLevel?.())
  // Subtitles, from the room rather than from a poll.
  //
  // Both sides of the conversation are already published here as a text stream,
  // incrementally, with the sender's identity and a final/interim flag. Reading
  // them from the two-second runtime poll instead meant a sentence that arrives
  // word by word was shown as a paragraph landing whole, after the moment it
  // described.
  try {
    room.registerTextStreamHandler(TRANSCRIPTION_TOPIC, async (reader, participant) => {
      const attributes = reader.info.attributes ?? {}
      // The local participant is the person; anything else in the room is the
      // agent. Comparing identities rather than guessing from the text.
      const role = participant?.identity === room.localParticipant.identity ? 'user' : 'marvi'
      const id = String(attributes[ATTR_SEGMENT] ?? reader.info.id ?? '')
      let text = ''
      for await (const chunk of reader) {
        text += chunk
        applyTranscript({
          role,
          text,
          final: String(attributes[ATTR_FINAL] ?? '') === 'true',
          id
        })
      }
    })
  } catch (cause) {
    // A handler already registered, or an SDK without the topic. Subtitles are
    // worth having and never worth failing a call for.
    console.warn('live transcript unavailable:', describe(cause))
  }
  room.on(RoomEvent.Disconnected, () => clearTranscript())

  if (room.state === ConnectionState.Connected) publishPhase('ready')

  // Every phase after this comes from the agent's `lk.agent.state`. If no
  // agent takes the job, none ever arrives and the orb sits on READY saying
  // "Say Marvi" -- identical to an agent that is up and waiting for you to
  // speak. That ambiguity hid a dispatch failure for days, so say it instead.
  const waiting = window.setTimeout(() => {
    const agent = [...room.remoteParticipants.values()].some(
      (participant) => participant.attributes[AGENT_STATE_ATTRIBUTE]
    )
    if (agent || room.state !== ConnectionState.Connected) return
    cycleVoicePhase('error')
    $voiceState.set({
      ...$voiceState.get(),
      caption: 'No agent joined',
      detail: 'The worker did not take the job'
    })
    window.marvi.publishVoiceState($voiceState.get())
  }, AGENT_JOIN_GRACE_MS)
  room.on(RoomEvent.Disconnected, () => window.clearTimeout(waiting))
  room.on(RoomEvent.ParticipantConnected, () => window.clearTimeout(waiting))
  return room
}
