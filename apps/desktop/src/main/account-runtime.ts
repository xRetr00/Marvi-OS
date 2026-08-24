import type { AccountPage } from '../shared/runtime'

/** Convert the Gateway's snake_case contract into renderer-owned types. */
export function normaliseAccountPage(body: unknown): AccountPage {
  const page = (body ?? {}) as Record<string, unknown>
  const sync = (page.sync ?? {}) as Record<string, unknown>
  const triggers = (page.triggers ?? {}) as Record<string, unknown>
  const providers = Array.isArray(sync.providers) ? sync.providers : []
  const connections = Array.isArray(sync.connections) ? sync.connections : []
  return {
    available: Boolean(page.available),
    detail: String(page.detail ?? ''),
    accounts: (Array.isArray(page.accounts) ? page.accounts : []).map((value) => {
      const row = value as Record<string, unknown>
      const scope = row.scope === 'admin' || row.scope === 'write' ? row.scope : 'read'
      return {
        id: String(row.id ?? ''),
        toolkit: String(row.toolkit ?? ''),
        status: String(row.status ?? ''),
        connected: Boolean(row.connected),
        needsReconnect: Boolean(row.needs_reconnect),
        alias: String(row.alias ?? ''),
        scope,
        syncEnabled: row.sync_enabled !== false
      }
    }),
    sync: {
      providers: providers.map((value) => {
        const row = value as Record<string, unknown>
        return { toolkit: String(row.toolkit ?? ''), label: String(row.label ?? row.toolkit ?? '') }
      }),
      connections: connections.map((value) => {
        const row = value as Record<string, unknown>
        return {
          toolkit: String(row.toolkit ?? ''),
          connectionId: String(row.connection_id ?? ''),
          cursor: String(row.cursor ?? ''),
          status: String(row.status ?? 'idle'),
          lastAttemptAt: row.last_attempt_at ? String(row.last_attempt_at) : null,
          lastSuccessAt: row.last_success_at ? String(row.last_success_at) : null,
          lastError: String(row.last_error ?? ''),
          itemsSeen: Number(row.items_seen ?? 0),
          lastCount: Number(row.last_count ?? 0)
        }
      })
    },
    triggers: {
      connected: Boolean(triggers.connected),
      received: Number(triggers.received ?? 0),
      lastEventAt: triggers.last_event_at ? String(triggers.last_event_at) : null,
      lastError: String(triggers.last_error ?? ''),
      transport: String(triggers.transport ?? 'composio-realtime')
    }
  }
}

/** Only Composio's HTTPS host may leave the Electron sandbox as an OAuth URL. */
export function isComposioConnectUrl(raw: string): boolean {
  try {
    const url = new URL(raw)
    return (
      url.protocol === 'https:' &&
      (url.hostname === 'composio.dev' || url.hostname.endsWith('.composio.dev'))
    )
  } catch {
    return false
  }
}
