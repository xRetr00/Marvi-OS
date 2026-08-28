import type { ConnectorRow, ConnectorsPage, ConnectorStatus } from '../shared/runtime'

const CONNECTOR_STATUSES: ConnectorStatus[] = ['connected', 'expired', 'disconnected', 'preview']

function normaliseConnectorStatus(value: unknown): ConnectorStatus {
  return CONNECTOR_STATUSES.includes(value as ConnectorStatus)
    ? (value as ConnectorStatus)
    : 'disconnected'
}

export function normaliseConnectorRow(value: unknown): ConnectorRow {
  const row = (value ?? {}) as Record<string, unknown>
  const scope = row.scope === 'admin' || row.scope === 'write' ? row.scope : 'read'
  return {
    slug: String(row.slug ?? ''),
    name: String(row.name ?? row.slug ?? ''),
    status: normaliseConnectorStatus(row.status),
    connectionId: String(row.connection_id ?? ''),
    scope,
    connections: Number(row.connections ?? 0),
    error: String(row.error ?? '')
  }
}

/** Convert the Gateway's snake_case `/connectors` contract into renderer-owned types. */
export function normaliseConnectorsPage(body: unknown): ConnectorsPage {
  const page = (body ?? {}) as Record<string, unknown>
  const connectors = Array.isArray(page.connectors) ? page.connectors : []
  return {
    available: Boolean(page.available),
    connectors: connectors.map(normaliseConnectorRow)
  }
}

/**
 * Only an https URL may leave the Electron sandbox as a connector authorization
 * link. Unlike Accounts, `/connectors` is not pinned to a single OAuth host —
 * different connector backends may live behind different domains — so this
 * checks the scheme only, the same bar every other outbound `shell.openExternal`
 * call in this file already holds itself to.
 */
export function isSafeConnectUrl(raw: string): boolean {
  try {
    return new URL(raw).protocol === 'https:'
  } catch {
    return false
  }
}
