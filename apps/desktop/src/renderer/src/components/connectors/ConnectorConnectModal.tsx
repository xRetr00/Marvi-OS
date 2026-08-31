import { useEffect } from 'react'

import type { ConnectorMeta } from '../../lib/connectors/connectorCatalog'
import { connectorMonogram } from '../../lib/connectors/connectorCatalog'
import { CONNECTOR_LOGOS } from '../../lib/connectors/connectorLogos'
import { useConnectorConnectFlow } from '../../hooks/useConnectorConnectFlow'
import { AbstractIcon } from '../abstract-icon'
import { ScopeToggles } from './ScopeToggles'
import type { ConnectorRow } from '../../../../shared/runtime'

const PHASE_COPY: Record<string, string> = {
  idle: 'Not connected yet.',
  'needs-fields': 'A few details are needed before authorizing.',
  authorizing: 'Opening your browser…',
  waiting: 'Waiting for authorization to finish in your browser.',
  connected: 'Connected.',
  connecting: 'Finishing the connection…',
  expired: 'Authorization expired. Reconnect to keep using this connector.',
  disconnecting: 'Disconnecting…',
  error: 'Something went wrong.'
}

/**
 * The connect flow surfaced in one modal: idle → authorizing → waiting
 * (poll-based, since connectors have no deep-link callback) → connected, with
 * a `needs-fields` recovery step for providers that need something more than
 * OAuth. Layout follows openhuman's `ComposioConnectModal`; tokens and
 * controls are Marvi's own.
 */
export function ConnectorConnectModal({
  meta,
  row,
  onChanged,
  onClose
}: {
  meta: ConnectorMeta
  row?: ConnectorRow
  onChanged: () => void
  onClose: () => void
}): React.JSX.Element {
  const flow = useConnectorConnectFlow({ slug: meta.slug, row, onChanged })

  useEffect(() => {
    const escape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', escape)
    return () => window.removeEventListener('keydown', escape)
  }, [onClose])

  const busy =
    flow.phase === 'authorizing' || flow.phase === 'waiting' || flow.phase === 'disconnecting'

  const Logo = CONNECTOR_LOGOS[meta.slug]

  return (
    <div
      className="connector-modal-shell"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      role="presentation"
    >
      <div
        aria-label={`${meta.name} connector`}
        aria-modal="true"
        className="connector-modal"
        role="dialog"
      >
        <button
          aria-label="Close"
          className="connector-modal-close"
          onClick={onClose}
          type="button"
        >
          <AbstractIcon name="close" size={14} />
        </button>

        <header className="connector-modal-head">
          {/* The same mark the card carries. The modal was left on the
              monogram, so opening a connector replaced its logo with two grey
              letters at the exact moment the user was looking hardest at it. */}
          <span
            aria-hidden="true"
            className="connector-card-logo"
            style={{ '--connector-tint': meta.tint } as React.CSSProperties}
          >
            {Logo ? <Logo height={19} width={19} /> : connectorMonogram(meta.name)}
          </span>
          <div>
            <h3>{meta.name}</h3>
            <p>{meta.permissionLabel}</p>
          </div>
        </header>

        <p className="connector-modal-phase">{PHASE_COPY[flow.phase]}</p>

        {flow.error ? <p className="connector-required-field-error">{flow.error}</p> : null}

        {(flow.phase === 'idle' || flow.phase === 'needs-fields' || flow.phase === 'error') &&
        flow.requiredFields.length > 0 ? (
          <div>
            {flow.requiredFields.map((field) => (
              <div className="connector-required-field" key={field.key}>
                <label htmlFor={`connector-field-${field.key}`}>{field.label}</label>
                <div className="connector-required-field-input">
                  <input
                    id={`connector-field-${field.key}`}
                    onChange={(event) => flow.setFieldValue(field.key, event.target.value)}
                    placeholder={field.placeholder}
                    type="text"
                    value={flow.fieldValues[field.key] ?? ''}
                  />
                  {field.suffix ? (
                    <span className="connector-required-field-suffix">{field.suffix}</span>
                  ) : null}
                </div>
                {field.hint ? <p className="connector-required-field-hint">{field.hint}</p> : null}
                {flow.fieldErrors[field.key] ? (
                  <p className="connector-required-field-error">{flow.fieldErrors[field.key]}</p>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}

        {flow.phase === 'connected' && row ? (
          <>
            <ScopeToggles
              disabled={false}
              onChange={(next) => {
                void window.marvi?.setConnectorScope(meta.slug, next).then(onChanged)
              }}
              scope={row.scope}
            />
            <div className="control-actions">
              <button
                className="phase danger"
                disabled={flow.phase !== 'connected'}
                onClick={() => void flow.handleDisconnect(row.connectionId)}
                type="button"
              >
                Disconnect
              </button>
            </div>
          </>
        ) : (
          <div className="control-actions">
            <button
              className="phase active"
              disabled={busy || flow.connectInFlight}
              onClick={() => void flow.handleConnect()}
              type="button"
            >
              {flow.phase === 'waiting'
                ? 'Waiting…'
                : flow.phase === 'expired'
                  ? 'Reconnect'
                  : 'Connect'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
