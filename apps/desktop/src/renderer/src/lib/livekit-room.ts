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

import { $voiceState, cycleVoicePhase, setVoiceLevel } from '../store/voice-state'

interface LiveKitConnection {
  url: string
  room: string
  token: string
}

const AGENT_STATE_ATTRIBUTE = 'lk.agent.state'

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

/** Set while `stopVoice` is hanging up, so the disconnect is not an error. */
let deliberate = false

export function expectDisconnect(): void {
  deliberate = true
}

export async function connectVoiceRoom(): Promise<Room> {
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
    audioCaptureDefaults: {
      autoGainControl: true,
      echoCancellation: true,
      noiseSuppression: true,
      channelCount: 1
    }
  })
  room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
    if (track.kind === Track.Kind.Audio) track.attach()
  })
  room.on(RoomEvent.ParticipantAttributesChanged, (_changed, participant) => {
    if (participant instanceof RemoteParticipant) applyAgentState(participant)
  })
  room.on(RoomEvent.ParticipantConnected, applyAgentState)
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
  try {
    await room.localParticipant.setMicrophoneEnabled(true, {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      channelCount: 1
    })
  } catch (cause) {
    await room.disconnect()
    throw new Error(`The microphone could not be opened: ${describe(cause)}`)
  }

  const micTrack = room.localParticipant.getTrackPublication(Track.Source.Microphone)
    ?.audioTrack as LocalAudioTrack | undefined
  let stopLevel: (() => void) | undefined
  if (micTrack) stopLevel = streamMicLevel(micTrack)
  room.on(RoomEvent.Disconnected, () => stopLevel?.())
  if (room.state === ConnectionState.Connected) publishPhase('ready')
  return room
}
