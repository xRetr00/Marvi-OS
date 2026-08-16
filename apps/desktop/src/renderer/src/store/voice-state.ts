import { atom } from 'nanostores'

import {
  ASSISTANT_PHASES,
  DEFAULT_ASSISTANT_STATE,
  OFFLINE_RUNTIME,
  type AssistantPhase,
  type AssistantState,
  type RuntimeStatus
} from '../../../shared/runtime'

export const VOICE_PHASES = ASSISTANT_PHASES
export type VoicePhase = AssistantPhase
export type VoiceState = AssistantState

const PHASE_COPY: Record<AssistantPhase, { caption: string; detail: string | null }> = {
  ready: { caption: 'Say Marvi', detail: null },
  wake: { caption: 'I am here', detail: 'Wake word accepted' },
  listening: { caption: 'Listening', detail: 'Talk naturally' },
  thinking: { caption: 'Thinking', detail: 'Connecting context' },
  speaking: { caption: 'Speaking', detail: 'Talk to interrupt' },
  action: { caption: 'Turning on the room light', detail: 'Smart Room' },
  notification: { caption: 'New message from Alex', detail: 'World context' },
  confirmation: { caption: 'Confirm action', detail: 'Send the drafted reply?' },
  error: { caption: 'Gateway unavailable', detail: 'Retrying locally' }
}

export const $runtimeState = atom<RuntimeStatus>(OFFLINE_RUNTIME)
export const $voiceState = atom<AssistantState>(DEFAULT_ASSISTANT_STATE)

export function applyRuntimeState(runtime: RuntimeStatus): void {
  $runtimeState.set(runtime)
  $voiceState.set(runtime.assistant)
}

export function cycleVoicePhase(phase: AssistantPhase): void {
  const copy = PHASE_COPY[phase]
  $voiceState.set({
    ...$voiceState.get(),
    phase,
    caption: copy.caption,
    detail: copy.detail,
    level:
      phase === 'listening' ? 0.72 : phase === 'speaking' ? 0.58 : phase === 'wake' ? 0.9 : 0.22,
    confirmation:
      phase === 'confirmation'
        ? {
            token: 'preview-confirmation',
            action: 'Send email reply',
            detail: 'To Alex · Re: Project update'
          }
        : null
  })
}
