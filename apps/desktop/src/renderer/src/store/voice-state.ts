import { atom } from 'nanostores'

export const VOICE_PHASES = ['ready', 'wake', 'listening', 'thinking', 'speaking'] as const
export type VoicePhase = (typeof VOICE_PHASES)[number]

export interface VoiceState {
  phase: VoicePhase
  caption: string
  level: number
}

const PHASE_COPY: Record<VoicePhase, string> = {
  ready: 'Say Marvi',
  wake: 'I am here',
  listening: 'Listening',
  thinking: 'Thinking',
  speaking: 'Speaking · talk to interrupt'
}

export const $voiceState = atom<VoiceState>({
  phase: 'ready',
  caption: PHASE_COPY.ready,
  level: 0.18
})

export function cycleVoicePhase(phase: VoicePhase): void {
  $voiceState.set({
    phase,
    caption: PHASE_COPY[phase],
    level:
      phase === 'listening' ? 0.72 : phase === 'speaking' ? 0.58 : phase === 'wake' ? 0.9 : 0.22
  })
}
