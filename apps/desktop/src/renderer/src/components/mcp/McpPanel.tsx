import { useCallback, useEffect, useState } from 'react'
import { Boxes, PackagePlus, Server, Trash2, Wrench } from 'lucide-react'

import { ControlEmpty, ControlPage, ControlPill, ControlSection } from '../control-surface'
import { McpInstallDialog } from './McpInstallDialog'
import { filterInstalledServers, filterRegistryServers } from '../capabilities/capability-library'
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

  const installedFiltered = filterInstalledServers(installed, query)
  const showInstalled = chip !== 'registry'
  const showRegistry = chip !== 'installed'
  const registryFiltered = filterRegistryServers(registry, installed, query)

  const empty = loaded && installedFiltered.length === 0 && registryFiltered.length === 0
  const connected = installed.filter((row) => row.status === 'connected').length
  const tools = installed.reduce((total, row) => total + row.tools, 0)

  return (
    <ControlPage
      className="capabilities-page"
      description="Local MCP servers Marvi can call as tools, installed or from the registry."
      title="MCP"
    >
      <div className="capability-overview" aria-label="MCP summary">
        <div>
          <span>Installed</span>
          <strong>{installed.length}</strong>
        </div>
        <div>
          <span>Connected</span>
          <strong>{connected}</strong>
        </div>
        <div>
          <span>Available tools</span>
          <strong>{tools}</strong>
        </div>
        <div>
          <span>Registry results</span>
          <strong>{registry.length}</strong>
        </div>
      </div>
      <ControlSection
        action={
          <ControlPill tone={installed.length > 0 ? 'ready' : 'neutral'}>
            {installed.length} installed
          </ControlPill>
        }
        description="Connected servers stay separate from installable registry entries."
        icon={Boxes}
        title="Server library"
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
            {showInstalled && installedFiltered.length > 0 ? (
              <section className="capability-library-section">
                <header>
                  <div>
                    <Server aria-hidden="true" size={15} />
                    <strong>Installed servers</strong>
                  </div>
                  <span>{installedFiltered.length}</span>
                </header>
                <div className="capability-card-grid">
                  {installedFiltered.map((row) => (
                    <article className="capability-card mcp-card" key={`installed-${row.id}`}>
                      <header className="capability-card-head">
                        <span className="capability-card-mark" aria-hidden="true">
                          <Server size={15} />
                          <i
                            className={`mcp-status-dot${row.status === 'connected' ? ' is-connected' : row.status === 'error' ? ' is-error' : ''}`}
                          />
                        </span>
                        <div>
                          <strong>{row.name}</strong>
                          <span>{row.id}</span>
                        </div>
                        <ControlPill tone={row.status === 'connected' ? 'ready' : 'danger'}>
                          {row.status}
                        </ControlPill>
                      </header>
                      <p>Tools exposed to Marvi through this local server.</p>
                      <div className="capability-card-meta">
                        <span>
                          {row.tools} tool{row.tools === 1 ? '' : 's'}
                        </span>
                        <span>Installed</span>
                      </div>
                      <footer className="capability-card-actions">
                        <button
                          className="phase danger"
                          disabled={busy === row.id}
                          onClick={() => void remove(row.id)}
                          type="button"
                        >
                          <Trash2 aria-hidden="true" size={13} /> Remove
                        </button>
                      </footer>
                    </article>
                  ))}
                </div>
              </section>
            ) : null}
            {showRegistry && registryFiltered.length > 0 ? (
              <section className="capability-library-section">
                <header>
                  <div>
                    <PackagePlus aria-hidden="true" size={15} />
                    <strong>Registry catalog</strong>
                  </div>
                  <span>{registryFiltered.length}</span>
                </header>
                <div className="capability-card-grid">
                  {registryFiltered.map((row) => (
                    <article
                      className="capability-card catalog-card mcp-card"
                      key={`registry-${row.qualifiedName}`}
                    >
                      <header className="capability-card-head">
                        <span className="capability-card-mark" aria-hidden="true">
                          <Wrench size={15} />
                        </span>
                        <div>
                          <strong>{row.name}</strong>
                          <span>{row.author || 'Registry publisher'}</span>
                        </div>
                        <ControlPill>Registry</ControlPill>
                      </header>
                      <p>{row.description || 'No description supplied by the publisher.'}</p>
                      <div className="capability-card-meta">
                        <span>{row.qualifiedName}</span>
                      </div>
                      <footer className="capability-card-actions">
                        <button
                          className="phase"
                          onClick={() => setInstallTarget(row)}
                          type="button"
                        >
                          Review and install
                        </button>
                      </footer>
                    </article>
                  ))}
                </div>
              </section>
            ) : null}
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
