import { atom } from 'nanostores'

import {
  ASSISTANT_PHASES,
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
  // Reasoning is forced off for voice, so there is nothing to think about --
  // this is the gap between the question ending and the first word coming
  // back, and calling it "Thinking" invites you to wait for deliberation that
  // is not happening. It should be brief enough to barely register.
  thinking: { caption: 'One moment', detail: null },
  speaking: { caption: 'Speaking', detail: 'Talk to interrupt' },
  action: { caption: 'Turning on the room light', detail: 'Smart Room' },
  notification: { caption: 'New message from Alex', detail: 'World context' },
  confirmation: { caption: 'Confirm action', detail: 'Send the drafted reply?' },
  error: { caption: 'Gateway unavailable', detail: 'Retrying locally' }
}

export const $runtimeState = atom<RuntimeStatus>(OFFLINE_RUNTIME)
// Nothing has answered yet when this is created, so it starts from the
// offline state rather than claiming to be ready.
export const $voiceState = atom<AssistantState>(OFFLINE_RUNTIME.assistant)

export function applyRuntimeState(runtime: RuntimeStatus): void {
  $runtimeState.set(runtime)
  $voiceState.set(runtime.assistant)
}

/**
 * Publish the live microphone level (0..1) without touching the phase. The
 * island and voice orbs read this continuously; the phase carries the state,
 * the level carries the energy.
 */
export function setVoiceLevel(level: number): void {
  const next = Math.max(0, Math.min(1, Number.isFinite(level) ? level : 0))
  const current = $voiceState.get()
  if (Math.abs(current.level - next) < 0.005) return
  $voiceState.set({ ...current, level: next })
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
            detail: 'To Alex · Re: Project update',
            tool: 'preview',
            arguments: {}
          }
        : null
  })
}
