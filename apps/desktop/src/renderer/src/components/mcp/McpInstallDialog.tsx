import { useState } from 'react'

import { AbstractIcon } from '../abstract-icon'
import type { McpRegistryServer } from '../../../../shared/runtime'

/**
 * Installs one registry server. The registry contract doesn't declare which
 * environment variables a server needs up front, so this collects free-form
 * key/value pairs rather than a fixed schema — closer to openhuman's
 * `InstallDialog` fallback path than its schema-driven happy path.
 */
export function McpInstallDialog({
  server,
  onClose,
  onInstalled
}: {
  server: McpRegistryServer
  onClose: () => void
  onInstalled: () => void
}): React.JSX.Element {
  const [rows, setRows] = useState<Array<{ key: string; value: string }>>([{ key: '', value: '' }])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const install = async (): Promise<void> => {
    setBusy(true)
    setError('')
    const env: Record<string, string> = {}
    for (const row of rows) {
      if (row.key.trim()) env[row.key.trim()] = row.value
    }
    const result = await window.marvi?.installMcpServer(server.qualifiedName, env)
    setBusy(false)
    if (result?.ok) {
      onInstalled()
      onClose()
    } else {
      setError(result?.detail || 'Install failed.')
    }
  }

  return (
    <div
      className="connector-modal-shell"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      role="presentation"
    >
      <div
        aria-label={`Install ${server.name}`}
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
          <div>
            <h3>{server.name}</h3>
            <p>{server.description || server.qualifiedName}</p>
          </div>
        </header>

        {error ? <p className="connector-required-field-error">{error}</p> : null}

        <div className="connector-required-field">
          <label>Environment variables (optional)</label>
          {rows.map((row, index) => (
            <div className="connector-required-field-input" key={index}>
              <input
                onChange={(event) => {
                  const next = [...rows]
                  next[index] = { ...next[index], key: event.target.value }
                  setRows(next)
                }}
                placeholder="KEY"
                type="text"
                value={row.key}
              />
              <input
                onChange={(event) => {
                  const next = [...rows]
                  next[index] = { ...next[index], value: event.target.value }
                  setRows(next)
                }}
                placeholder="value"
                type="text"
                value={row.value}
              />
            </div>
          ))}
          <button
            className="phase"
            onClick={() => setRows([...rows, { key: '', value: '' }])}
            type="button"
          >
            Add variable
          </button>
        </div>

        <div className="control-actions">
          <button
            className="phase active"
            disabled={busy}
            onClick={() => void install()}
            type="button"
          >
            {busy ? 'Installing…' : 'Install'}
          </button>
        </div>
      </div>
    </div>
  )
}
