import type { ConnectorMeta } from '../../lib/connectors/connectorCatalog'
import { connectorMonogram } from '../../lib/connectors/connectorCatalog'
import type { ConnectorStatus } from '../../../../shared/runtime'

const STATUS_WORD: Record<ConnectorStatus, string> = {
  connected: 'Connected',
  expired: 'Auth expired',
  preview: 'Preview',
  disconnected: 'Not connected'
}

/**
 * One square card in the Connectors grid. Status is carried by the card's
 * border and tint rather than a separate icon — connected reads green,
 * expired auth reads red, preview reads amber, and an unconnected card stays
 * plain — with the status word underneath as the accessible fallback for
 * anyone who can't rely on color alone.
 */
export function ConnectorCard({
  meta,
  status,
  connections,
  onSelect
}: {
  meta: ConnectorMeta
  status: ConnectorStatus
  /** Active connection count. A badge only appears above one — a single
   * connection is already implied by "Connected". */
  connections: number
  onSelect: () => void
}): React.JSX.Element {
  return (
    <button
      aria-label={`${meta.name} · ${STATUS_WORD[status]}`}
      className={`connector-card is-${status}`}
      onClick={onSelect}
      type="button"
    >
      {connections > 1 ? <span className="connector-card-badge">{connections}</span> : null}
      <span aria-hidden="true" className="connector-card-logo">
        {connectorMonogram(meta.name)}
      </span>
      <span className="connector-card-name">{meta.name}</span>
      <span className="connector-card-status">{STATUS_WORD[status]}</span>
    </button>
  )
}
