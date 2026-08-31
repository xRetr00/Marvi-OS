import type { ConnectorMeta } from '../../lib/connectors/connectorCatalog'
import { connectorMonogram } from '../../lib/connectors/connectorCatalog'
import { CONNECTOR_LOGOS } from '../../lib/connectors/connectorLogos'
import type { ConnectorStatus } from '../../../../shared/runtime'

const STATUS_WORD: Record<ConnectorStatus, string> = {
  connected: 'Connected',
  // Composio is still setting it up. This used to read "Auth expired", which
  // told the user their brand-new connector was broken while it was two
  // seconds from working.
  connecting: 'Connecting…',
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
  const Logo = CONNECTOR_LOGOS[meta.slug]
  return (
    <button
      aria-label={`${meta.name} · ${STATUS_WORD[status]}`}
      className={`connector-card is-${status}`}
      onClick={onSelect}
      type="button"
    >
      {connections > 1 ? <span className="connector-card-badge">{connections}</span> : null}
      {/* The real mark where there is one, the tinted monogram where there is
          not. Both are inline SVG or text, never an <img>: the renderer's CSP
          is `img-src 'self' data:`, so nothing here can be fetched. */}
      <span
        aria-hidden="true"
        className="connector-card-logo"
        style={{ '--connector-tint': meta.tint } as React.CSSProperties}
      >
        {Logo ? <Logo height={19} width={19} /> : connectorMonogram(meta.name)}
      </span>
      <span className="connector-card-name">{meta.name}</span>
      <span className="connector-card-status">{STATUS_WORD[status]}</span>
    </button>
  )
}
