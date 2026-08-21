import { atom } from 'nanostores'

import type { ProviderPage } from '../../../shared/runtime'

export interface SessionMetrics {
  startedAt: number
  elapsedMs: number
  billableTokens: number
  cachedTokens: number
  chatTurns: number
  voiceTurns: number
  lastLatencyMs: number | null
  ready: boolean
}

let startedAt = Date.now()

export const $sessionMetrics = atom<SessionMetrics>({
  startedAt,
  elapsedMs: 0,
  billableTokens: 0,
  cachedTokens: 0,
  chatTurns: 0,
  voiceTurns: 0,
  lastLatencyMs: null,
  ready: false
})

let baseline: ProviderPage['totals'] | null = null
let previousVoicePhase = ''
let voiceTurnStartedAt: number | null = null

export function updateSessionUsage(totals: ProviderPage['totals']): void {
  if (!baseline) baseline = { ...totals }
  $sessionMetrics.set({
    ...$sessionMetrics.get(),
    billableTokens: Math.max(0, totals.billable - baseline.billable),
    cachedTokens: Math.max(0, totals.cachedInput - baseline.cachedInput),
    ready: true
  })
}

export function tickSession(now = Date.now()): void {
  $sessionMetrics.set({ ...$sessionMetrics.get(), elapsedMs: Math.max(0, now - startedAt) })
}

export function recordChatTurn(latencyMs: number): void {
  const current = $sessionMetrics.get()
  $sessionMetrics.set({
    ...current,
    chatTurns: current.chatTurns + 1,
    lastLatencyMs: Math.max(0, Math.round(latencyMs))
  })
}

export function observeVoicePhase(phase: string, now = Date.now()): void {
  if (phase === previousVoicePhase) return
  if (phase === 'listening' || phase === 'wake') voiceTurnStartedAt = now
  if (phase === 'speaking') {
    const current = $sessionMetrics.get()
    $sessionMetrics.set({
      ...current,
      voiceTurns: current.voiceTurns + 1,
      lastLatencyMs: voiceTurnStartedAt === null ? current.lastLatencyMs : now - voiceTurnStartedAt
    })
    voiceTurnStartedAt = null
  }
  previousVoicePhase = phase
}

export function formatSessionDuration(elapsedMs: number): string {
  const seconds = Math.max(0, Math.floor(elapsedMs / 1000))
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  const tail = `${String(minutes % 60).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
  return hours > 0 ? `${String(hours).padStart(2, '0')}:${tail}` : tail
}

export function sessionTimingStats(
  metrics: SessionMetrics
): Array<{ label: string; value: string }> {
  return [
    { label: 'TOKENS', value: metrics.ready ? metrics.billableTokens.toLocaleString() : '—' },
    { label: 'TURNS', value: String(metrics.chatTurns + metrics.voiceTurns) },
    { label: 'LAST', value: metrics.lastLatencyMs === null ? '—' : `${metrics.lastLatencyMs}ms` },
    { label: 'SESSION', value: formatSessionDuration(metrics.elapsedMs) }
  ]
}

/** Starts a fresh renderer session. Exported so behavior tests can isolate state. */
export function resetSessionMetrics(now = Date.now()): void {
  startedAt = now
  baseline = null
  previousVoicePhase = ''
  voiceTurnStartedAt = null
  $sessionMetrics.set({
    startedAt,
    elapsedMs: 0,
    billableTokens: 0,
    cachedTokens: 0,
    chatTurns: 0,
    voiceTurns: 0,
    lastLatencyMs: null,
    ready: false
  })
}
