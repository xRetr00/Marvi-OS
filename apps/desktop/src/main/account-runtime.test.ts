import { describe, expect, it } from 'vitest'

import { isComposioConnectUrl, normaliseAccountPage } from './account-runtime'

describe('account lifecycle bridge', () => {
  it('only opens Composio HTTPS authorization links', () => {
    expect(isComposioConnectUrl('https://connect.composio.dev/link/abc')).toBe(true)
    expect(isComposioConnectUrl('http://connect.composio.dev/link/abc')).toBe(false)
    expect(isComposioConnectUrl('https://composio.dev.evil.example/link/abc')).toBe(false)
    expect(isComposioConnectUrl('javascript:alert(1)')).toBe(false)
  })

  it('preserves capability and sync health across the IPC boundary', () => {
    const page = normaliseAccountPage({
      available: true,
      detail: '1 connected',
      accounts: [
        {
          id: 'ca_1',
          toolkit: 'gmail',
          status: 'ACTIVE',
          connected: true,
          needs_reconnect: false,
          scope: 'write',
          sync_enabled: true
        }
      ],
      sync: {
        providers: [{ toolkit: 'gmail', label: 'Gmail' }],
        connections: [
          {
            toolkit: 'gmail',
            connection_id: 'ca_1',
            cursor: '123',
            status: 'ready',
            last_success_at: '2026-08-24T10:00:00Z',
            items_seen: 4,
            last_count: 1
          }
        ]
      },
      triggers: { connected: true, received: 2, transport: 'composio-realtime' }
    })

    expect(page.accounts[0]).toMatchObject({ id: 'ca_1', scope: 'write', syncEnabled: true })
    expect(page.sync.connections[0]).toMatchObject({ connectionId: 'ca_1', itemsSeen: 4 })
    expect(page.triggers).toMatchObject({ connected: true, received: 2 })
  })
})
