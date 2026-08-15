import { beforeEach, describe, expect, it } from 'vitest'

import { $voiceState, cycleVoicePhase } from './voice-state'

describe('voice state', () => {
  beforeEach(() => cycleVoicePhase('ready'))

  it('exposes the barge-in affordance while speaking', () => {
    cycleVoicePhase('speaking')

    expect($voiceState.get()).toEqual({
      phase: 'speaking',
      caption: 'Speaking · talk to interrupt',
      level: 0.58
    })
  })

  it('returns to a quiet always-on ready state', () => {
    cycleVoicePhase('listening')
    cycleVoicePhase('ready')

    expect($voiceState.get().phase).toBe('ready')
    expect($voiceState.get().caption).toBe('Say Marvi')
  })
})
