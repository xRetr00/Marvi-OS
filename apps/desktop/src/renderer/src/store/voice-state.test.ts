import { beforeEach, describe, expect, it } from 'vitest'

import { $voiceState, cycleVoicePhase } from './voice-state'

describe('voice state', () => {
  beforeEach(() => cycleVoicePhase('ready'))

  it('exposes the barge-in affordance while speaking', () => {
    cycleVoicePhase('speaking')

    expect($voiceState.get()).toMatchObject({
      phase: 'speaking',
      caption: 'Speaking',
      detail: 'Talk to interrupt',
      level: 0.58
    })
  })

  it('returns to a quiet always-on ready state', () => {
    cycleVoicePhase('listening')
    cycleVoicePhase('ready')

    expect($voiceState.get().phase).toBe('ready')
    expect($voiceState.get().caption).toBe('Say Marvi')
  })

  it('creates an exact preview confirmation request', () => {
    cycleVoicePhase('confirmation')

    expect($voiceState.get().confirmation).toEqual({
      token: 'preview-confirmation',
      action: 'Send email reply',
      detail: 'To Alex · Re: Project update',
      tool: 'preview',
      arguments: {}
    })
  })
})
