import { beforeEach, describe, expect, it } from 'vitest'

import type { ProviderPage } from '../../../shared/runtime'

import {
  $sessionMetrics,
  formatSessionDuration,
  observeVoicePhase,
  recordChatTurn,
  resetSessionMetrics,
  sessionTimingStats,
  tickSession,
  updateSessionUsage
} from './session-metrics'

const totals = (billable: number, cachedInput = 0): ProviderPage['totals'] => ({
  input: billable + cachedInput,
  output: 0,
  cachedInput,
  billable
})

describe('session metrics', () => {
  beforeEach(() => resetSessionMetrics(1_000))

  it('counts authoritative provider usage from the session baseline', () => {
    updateSessionUsage(totals(100, 40))
    updateSessionUsage(totals(175, 55))

    expect($sessionMetrics.get().billableTokens).toBe(75)
    expect($sessionMetrics.get().cachedTokens).toBe(15)
  })

  it('keeps chat and voice turns in the same running session', () => {
    recordChatTurn(418.6)
    observeVoicePhase('listening', 2_000)
    observeVoicePhase('thinking', 2_300)
    observeVoicePhase('speaking', 2_740)

    expect($sessionMetrics.get()).toMatchObject({
      chatTurns: 1,
      voiceTurns: 1,
      lastLatencyMs: 740
    })
  })

  it('does not count repeated speaking snapshots as new turns', () => {
    observeVoicePhase('listening', 2_000)
    observeVoicePhase('speaking', 2_500)
    observeVoicePhase('speaking', 2_700)
    expect($sessionMetrics.get().voiceTurns).toBe(1)
  })

  it('formats the compact stats used on Chat and Voice', () => {
    updateSessionUsage(totals(10))
    updateSessionUsage(totals(42))
    tickSession(126_000)
    recordChatTurn(320)

    expect(formatSessionDuration(125_000)).toBe('02:05')
    expect(sessionTimingStats($sessionMetrics.get())).toEqual([
      { label: 'TOKENS', value: '32' },
      { label: 'TURNS', value: '1' },
      { label: 'LAST', value: '320ms' },
      { label: 'SESSION', value: '02:05' }
    ])
  })
})
