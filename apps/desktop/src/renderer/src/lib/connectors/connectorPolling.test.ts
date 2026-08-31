import { describe, expect, it } from 'vitest'

import {
  POLL_INTERVAL_MAX_MS,
  POLL_INTERVAL_START_MS,
  initialPhaseForStatus,
  nextPollIntervalMs,
  phaseForStatus
} from './connectorPolling'

describe('connector poll cadence', () => {
  it('backs off by the documented factor toward the cap', () => {
    let interval = POLL_INTERVAL_START_MS
    interval = nextPollIntervalMs(interval)
    expect(interval).toBe(2_250)
    interval = nextPollIntervalMs(interval)
    expect(interval).toBe(3_375)
    interval = nextPollIntervalMs(interval)
    expect(interval).toBe(POLL_INTERVAL_MAX_MS)
  })

  it('never exceeds the cap once it is reached', () => {
    expect(nextPollIntervalMs(POLL_INTERVAL_MAX_MS)).toBe(POLL_INTERVAL_MAX_MS)
  })

  it('maps a connected status to the connected phase', () => {
    expect(phaseForStatus('connected')).toBe('connected')
  })

  it('maps an expired status to the expired phase', () => {
    expect(phaseForStatus('expired')).toBe('expired')
  })

  it('keeps waiting on a disconnected or preview status', () => {
    expect(phaseForStatus('disconnected')).toBeNull()
    expect(phaseForStatus('preview')).toBeNull()
  })

  it('derives the initial phase from the last-known status without a poll', () => {
    expect(initialPhaseForStatus('connected')).toBe('connected')
    expect(initialPhaseForStatus('expired')).toBe('expired')
    expect(initialPhaseForStatus('disconnected')).toBe('idle')
    expect(initialPhaseForStatus(undefined)).toBe('idle')
  })
})

describe('a connection that is still being set up', () => {
  it('is not treated as expired', () => {
    // Composio reports INITIALIZING during the handshake, and every status
    // that was not live used to fall through to "expired". Connecting a
    // calendar showed "Authorization expired. Reconnect to keep using this
    // connector." over a connection that was two seconds from working, with a
    // Reconnect button under it, and then it turned green on its own.
    expect(phaseForStatus('connecting')).toBeNull()
  })

  it('picks up the wait when the modal is opened on one', () => {
    // Rather than offering a fresh authorization the user does not need.
    expect(initialPhaseForStatus('connecting')).toBe('waiting')
  })
})
