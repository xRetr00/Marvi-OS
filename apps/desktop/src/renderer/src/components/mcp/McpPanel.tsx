import { useCallback, useEffect, useState } from 'react'
import { Boxes, PackagePlus, Server, Trash2 } from 'lucide-react'

import { ControlEmpty, ControlPage, ControlPill, ControlSection } from '../control-surface'
import { McpInstallDialog } from './McpInstallDialog'
import { filterInstalledServers, filterRegistryServers } from '../capabilities/capability-library'
import type { McpInstalledServer, McpRegistryServer } from '../../../../shared/runtime'

type McpStoreTab = 'installed' | 'registry'

const STORE_TABS: Array<{ key: McpStoreTab; label: string; detail: string }> = [
  { key: 'installed', label: 'Installed', detail: 'Local servers' },
  { key: 'registry', label: 'Registry', detail: 'Server store' }
]

export function McpPanel(): React.JSX.Element {
  const [installed, setInstalled] = useState<McpInstalledServer[]>([])
  const [registry, setRegistry] = useState<McpRegistryServer[]>([])
  const [loaded, setLoaded] = useState(false)
  const [storeTab, setStoreTab] = useState<McpStoreTab>('installed')
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
    if (storeTab === 'installed') return
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
  }, [storeTab, query, loadRegistry])

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
  const registryFiltered = filterRegistryServers(registry, installed, query)

  const empty =
    loaded &&
    (storeTab === 'installed' ? installedFiltered.length === 0 : registryFiltered.length === 0)
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
      <div className="capability-store-tabs" role="tablist" aria-label="MCP stores">
        {STORE_TABS.map((tab) => (
          <button
            aria-selected={storeTab === tab.key}
            className="capability-store-tab"
            key={tab.key}
            onClick={() => setStoreTab(tab.key)}
            role="tab"
            type="button"
          >
            {tab.key === 'installed' ? (
              <Server aria-hidden="true" size={14} />
            ) : (
              <PackagePlus aria-hidden="true" size={14} />
            )}
            <span>
              <strong>{tab.label}</strong>
              <small>{tab.detail}</small>
            </span>
          </button>
        ))}
      </div>
      <ControlSection
        action={
          <ControlPill
            tone={
              storeTab === 'installed' && installed.length > 0
                ? 'ready'
                : storeTab === 'registry'
                  ? 'accent'
                  : 'neutral'
            }
          >
            {storeTab === 'installed'
              ? `${installed.length} installed`
              : `${registryFiltered.length} results`}
          </ControlPill>
        }
        description={
          storeTab === 'installed'
            ? 'Servers currently configured on this device.'
            : 'Discover public servers and review their configuration before installation.'
        }
        icon={Boxes}
        title={storeTab === 'installed' ? 'Installed servers' : 'MCP registry'}
      >
        <div className="capability-store-banner">
          <div>
            <span>{storeTab === 'installed' ? 'LOCAL LIBRARY' : 'SERVER STORE'}</span>
            <strong>{storeTab === 'installed' ? 'Configured MCP servers' : 'MCP registry'}</strong>
            <p>
              {storeTab === 'installed'
                ? 'Inspect connection state, available tools, and remove servers you no longer use.'
                : 'Browse public server metadata, then review environment variables before installing.'}
            </p>
          </div>
          <span className="capability-store-number">
            {String(storeTab === 'installed' ? installed.length : registry.length).padStart(2, '0')}
          </span>
        </div>
        <div className="capability-toolbar">
          <input
            aria-label="Search MCP servers"
            className="capability-search"
            onChange={(event) => setQuery(event.target.value)}
            placeholder={
              storeTab === 'installed' ? 'Search installed servers…' : 'Search the registry…'
            }
            type="search"
            value={query}
          />
          <span className="capability-source-count">
            {storeTab === 'installed' ? 'ON THIS DEVICE' : 'PUBLIC CATALOG'}
          </span>
        </div>

        {!loaded ? null : empty ? (
          <ControlEmpty
            description={
              storeTab === 'installed'
                ? 'Open the Registry tab to add a server, or check the Gateway connection.'
                : 'Try another search or check the registry connection.'
            }
            icon={Server}
            title={storeTab === 'installed' ? 'No installed servers' : 'No registry matches'}
          />
        ) : (
          <>
            {storeTab === 'installed' && installedFiltered.length > 0 ? (
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
            {storeTab === 'registry' && registryFiltered.length > 0 ? (
              <section className="capability-library-section">
                <header>
                  <div>
                    <PackagePlus aria-hidden="true" size={15} />
                    <strong>Registry catalog</strong>
                  </div>
                  <span>{registryFiltered.length}</span>
                </header>
                <div className="capability-card-grid capability-store-grid">
                  {registryFiltered.map((row, index) => (
                    <article
                      className={`capability-card catalog-card mcp-card capability-store-card${index === 0 ? ' is-featured' : ''}`}
                      key={`registry-${row.qualifiedName}`}
                    >
                      <header className="capability-card-head">
                        <span className="capability-card-mark" aria-hidden="true">
                          <span>{String(index + 1).padStart(2, '0')}</span>
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
