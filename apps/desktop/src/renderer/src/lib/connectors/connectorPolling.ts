import type { ConnectorStatus } from '../../../../shared/runtime'

/**
 * Confirmation is purely poll-based: connectors have no deep-link callback
 * into this desktop app, so after opening the browser the only way to learn
 * the OAuth handoff finished is to keep asking the Gateway. The cadence
 * starts fast and backs off toward a cap so a long wait doesn't hammer the
 * Gateway, and a window focus / tab-visible event — the user switching back
 * after authorizing, a near-perfect "just finished" signal — resets it to
 * fast for an immediate re-poll. Exact cadence and reasoning mirror
 * openhuman's `useComposioConnectFlow`.
 */
export const POLL_INTERVAL_START_MS = 1_500
export const POLL_INTERVAL_MAX_MS = 4_000
export const POLL_BACKOFF_FACTOR = 1.5
export const POLL_TIMEOUT_MS = 5 * 60 * 1_000

/** The next poll delay, backed off toward the cap. Pure so the cadence itself is testable. */
export function nextPollIntervalMs(currentMs: number): number {
  return Math.min(POLL_INTERVAL_MAX_MS, Math.round(currentMs * POLL_BACKOFF_FACTOR))
}

export type ConnectPhase =
  | 'idle'
  | 'needs-fields'
  | 'authorizing'
  | 'waiting'
  | 'connected'
  | 'expired'
  | 'disconnecting'
  | 'error'

/** Map a freshly-polled Gateway status onto the connect flow's phase, or null to keep waiting. */
export function phaseForStatus(status: ConnectorStatus): ConnectPhase | null {
  if (status === 'connected') return 'connected'
  // Still setting up, which is what "waiting" already means here. Returning
  // null keeps the poll going rather than declaring anything about it.
  if (status === 'connecting') return null
  if (status === 'expired') return 'expired'
  if (status === 'disconnected') return null
  // 'preview' connectors are visible but not yet authorizable — surfaced as
  // idle rather than left in an indefinite "waiting" state.
  return null
}

export function initialPhaseForStatus(status: ConnectorStatus | undefined): ConnectPhase {
  if (status === 'connected') return 'connected'
  // Opening the modal on a half-finished connection picks up the wait rather
  // than starting a new authorization the user does not need.
  if (status === 'connecting') return 'waiting'
  if (status === 'expired') return 'expired'
  return 'idle'
}
