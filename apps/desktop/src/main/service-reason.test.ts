import { describe, expect, it } from 'vitest'

import type { RuntimeStatus, ServiceReport } from '../shared/runtime'

/**
 * The boot-failure screen said "Marvi Gateway unavailable" while the
 * supervisor was holding the actual answer: `port 8765 is already taken by
 * process 31816`.
 *
 * The status is built from a failed HTTP poll, which knows only that nothing
 * answered. A poll cannot tell a Gateway that is starting from one that will
 * never start; the supervisor can, and it is two objects away.
 */
function withServiceReason(status: RuntimeStatus, reports: ServiceReport[]): RuntimeStatus {
  const report = reports.find((service) => service.name === 'gateway')
  if (!report || !report.detail) return status
  if (report.state !== 'failed' && report.state !== 'gave up') return status
  return {
    ...status,
    components: { ...status.components, gateway: { state: 'error', detail: report.detail } }
  }
}

const offline = {
  components: { gateway: { state: 'offline', detail: 'Marvi Gateway unavailable' } }
} as unknown as RuntimeStatus

const report = (state: string, detail: string): ServiceReport =>
  ({ name: 'gateway', state, detail }) as unknown as ServiceReport

describe('explaining an unreachable gateway', () => {
  it('uses the supervisor’s reason when the service has given up', () => {
    const taken = 'port 8765 is already taken by process 31816 (D:\Marvi-OS\.venv\python.exe)'
    const status = withServiceReason(offline, [report('gave up', taken)])

    expect(status.components.gateway.detail).toBe(taken)
    expect(status.components.gateway.state).toBe('error')
  })

  it('keeps the generic message while the service is still trying', () => {
    // Starting and never-going-to-start look identical to a poll, and only one
    // of them is worth alarming somebody about.
    const status = withServiceReason(offline, [report('starting', 'launching uv')])

    expect(status.components.gateway.detail).toBe('Marvi Gateway unavailable')
  })

  it('keeps it when there is no report at all', () => {
    expect(withServiceReason(offline, []).components.gateway.detail).toBe(
      'Marvi Gateway unavailable'
    )
  })
})
