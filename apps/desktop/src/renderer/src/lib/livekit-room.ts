import {
  ConnectionState,
  RemoteParticipant,
  Room,
  RoomEvent,
  Track,
  type RemoteTrack
} from 'livekit-client'

import { $voiceState, cycleVoicePhase } from '../store/voice-state'

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

export async function connectVoiceRoom(): Promise<Room> {
  let connection: LiveKitConnection | undefined
  for (let attempt = 0; attempt < 30; attempt += 1) {
    try {
      connection = await window.marvi.getVoiceSession()
      break
    } catch {
      await new Promise((resolve) => window.setTimeout(resolve, 1_000))
    }
  }
  if (!connection) throw new Error('Marvi Gateway did not become ready')
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
  room.on(RoomEvent.Disconnected, () => publishPhase('error'))
  room.on(RoomEvent.Reconnecting, () => publishPhase('wake'))
  room.on(RoomEvent.Reconnected, () => publishPhase('ready'))
  await room.connect(connection.url, connection.token, { autoSubscribe: true })
  await room.localParticipant.setMicrophoneEnabled(true, {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
    channelCount: 1
  })
  if (room.state === ConnectionState.Connected) publishPhase('ready')
  return room
}
