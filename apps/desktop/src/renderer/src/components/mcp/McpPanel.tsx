import { useCallback, useEffect, useState } from 'react'
import { Server, Trash2 } from 'lucide-react'

import {
  ControlEmpty,
  ControlPage,
  ControlPill,
  ControlRow,
  ControlSection
} from '../control-surface'
import { McpInstallDialog } from './McpInstallDialog'
import type { McpInstalledServer, McpRegistryServer } from '../../../../shared/runtime'

type Chip = 'all' | 'installed' | 'registry'

const CHIPS: Array<{ key: Chip; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'installed', label: 'Installed' },
  { key: 'registry', label: 'Registry' }
]

/**
 * Capabilities > MCP. Unified list over installed servers and the registry
 * catalog, filtered by the same "All / Installed / Registry" chips
 * openhuman's `McpServersTab` uses — Marvi renders it as a row list via the
 * shared `ControlRow` primitive instead of a dedicated table component.
 */
export function McpPanel(): React.JSX.Element {
  const [installed, setInstalled] = useState<McpInstalledServer[]>([])
  const [registry, setRegistry] = useState<McpRegistryServer[]>([])
  const [loaded, setLoaded] = useState(false)
  const [chip, setChip] = useState<Chip>('all')
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState('')
  const [installTarget, setInstallTarget] = useState<McpRegistryServer | null>(null)

  const loadInstalled = useCallback(async (): Promise<void> => {
    const page = await window.marvi?.getMcpServers()
    setLoaded(true)
    if (page) setInstalled(page.servers)
  }, [])

  const loadRegistry = useCallback(async (search: string): Promise<void> => {
    const page = await window.marvi?.getMcpRegistry(search, 1)
    if (page) setRegistry(page.servers)
  }, [])

  useEffect(() => {
    let disposed = false
    void (async () => {
      if (!disposed) await loadInstalled()
    })()
    return () => {
      disposed = true
    }
  }, [loadInstalled])

  useEffect(() => {
    if (chip === 'installed') return
    let disposed = false
    const timer = setTimeout(() => {
      void (async () => {
        if (!disposed) await loadRegistry(query)
      })()
    }, 250)
    return () => {
      disposed = true
      clearTimeout(timer)
    }
  }, [chip, query, loadRegistry])

  const remove = async (id: string): Promise<void> => {
    setBusy(id)
    try {
      const ok = await window.marvi?.deleteMcpServer(id)
      if (ok) await loadInstalled()
    } finally {
      setBusy('')
    }
  }

  const needle = query.trim().toLowerCase()
  const installedFiltered = installed.filter(
    (row) => !needle || row.name.toLowerCase().includes(needle)
  )
  const showInstalled = chip !== 'registry'
  const showRegistry = chip !== 'installed'
  const installedSlugs = new Set(installed.map((row) => row.name.toLowerCase()))
  const registryFiltered = registry.filter((row) => !installedSlugs.has(row.name.toLowerCase()))

  const empty = loaded && installedFiltered.length === 0 && registryFiltered.length === 0

  return (
    <ControlPage
      className="capabilities-page"
      description="Local MCP servers Marvi can call as tools, installed or from the registry."
      title="MCP"
    >
      <ControlSection
        action={
          <ControlPill tone={installed.length > 0 ? 'ready' : 'neutral'}>
            {installed.length} installed
          </ControlPill>
        }
        icon={Server}
        title="MCP servers"
      >
        <div className="capability-toolbar">
          <input
            aria-label="Search MCP servers"
            className="capability-search"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search servers…"
            type="search"
            value={query}
          />
          <div className="capability-chips" role="group" aria-label="Filter">
            {CHIPS.map((option) => (
              <button
                aria-pressed={chip === option.key}
                className="capability-chip"
                key={option.key}
                onClick={() => setChip(option.key)}
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        {!loaded ? null : empty ? (
          <ControlEmpty
            description="Install one from the registry, or check the Gateway connection."
            icon={Server}
            title="No MCP servers found"
          />
        ) : (
          <>
            {showInstalled &&
              installedFiltered.map((row) => (
                <ControlRow
                  action={
                    <button
                      className="phase danger"
                      disabled={busy === row.id}
                      onClick={() => void remove(row.id)}
                      type="button"
                    >
                      <Trash2 aria-hidden="true" size={13} /> Remove
                    </button>
                  }
                  description={`${row.tools} tool${row.tools === 1 ? '' : 's'}`}
                  key={`installed-${row.id}`}
                  title={
                    <span>
                      <span
                        aria-hidden="true"
                        className={`mcp-status-dot${row.status === 'connected' ? ' is-connected' : row.status === 'error' ? ' is-error' : ''}`}
                      />
                      {row.name}
                    </span>
                  }
                />
              ))}
            {showRegistry &&
              registryFiltered.map((row) => (
                <ControlRow
                  action={
                    <button className="phase" onClick={() => setInstallTarget(row)} type="button">
                      Install
                    </button>
                  }
                  description={`${row.description || row.qualifiedName}${row.author ? ` · ${row.author}` : ''}`}
                  key={`registry-${row.qualifiedName}`}
                  title={row.name}
                />
              ))}
          </>
        )}
      </ControlSection>

      {installTarget ? (
        <McpInstallDialog
          onClose={() => setInstallTarget(null)}
          onInstalled={() => void loadInstalled()}
          server={installTarget}
        />
      ) : null}
    </ControlPage>
  )
}
