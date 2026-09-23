import { t } from '../../store/locale'
import { Tr } from '../../store/locale'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Boxes, PackagePlus, Server, Trash2 } from 'lucide-react'

import { ControlEmpty, ControlPage, ControlPill, ControlSection } from '../control-surface'
import { McpInstallDialog } from './McpInstallDialog'
import {
  filterInstalledServers,
  filterRegistryServers,
  mergeRegistryServers
} from '../capabilities/capability-library'
import type { McpInstalledServer, McpRegistryServer } from '../../../../shared/runtime'
import { TechnicalText } from '../ui/technical-text'

type McpStoreTab = 'installed' | 'registry'

const STORE_TABS: Array<{ key: McpStoreTab; label: string; detail: string }> = [
  { key: 'installed', label: 'Installed', detail: 'Local servers' },
  { key: 'registry', label: 'Registry', detail: 'Server store' }
]

export function McpPanel(): React.JSX.Element {
  const [installed, setInstalled] = useState<McpInstalledServer[]>([])
  const [registry, setRegistry] = useState<McpRegistryServer[]>([])
  const [registryPage, setRegistryPage] = useState(0)
  const [registryTotalPages, setRegistryTotalPages] = useState(1)
  const [loadingRegistry, setLoadingRegistry] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [storeTab, setStoreTab] = useState<McpStoreTab>('installed')
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState('')
  const [installTarget, setInstallTarget] = useState<McpRegistryServer | null>(null)
  const registryRequest = useRef(0)

  const loadInstalled = useCallback(async (): Promise<void> => {
    const page = await window.marvi?.getMcpServers()
    setLoaded(true)
    if (page) setInstalled(page.servers)
  }, [])

  const loadRegistry = useCallback(
    async (search: string, pageNumber = 1, append = false): Promise<void> => {
      const requestId = ++registryRequest.current
      setLoadingRegistry(true)
      try {
        const page = await window.marvi?.getMcpRegistry(search, pageNumber)
        if (!page || requestId !== registryRequest.current) return
        setRegistry((current) => mergeRegistryServers(current, page.servers, append))
        setRegistryPage(pageNumber)
        setRegistryTotalPages(page.totalPages)
      } finally {
        if (requestId === registryRequest.current) setLoadingRegistry(false)
      }
    },
    []
  )

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
        if (!disposed) await loadRegistry(query, 1, false)
      })()
    }, 250)
    return () => {
      disposed = true
      registryRequest.current += 1
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
    (storeTab === 'installed' || registryPage > 0) &&
    !loadingRegistry &&
    (storeTab === 'installed' ? installedFiltered.length === 0 : registryFiltered.length === 0)
  const connected = installed.filter((row) => row.status === 'connected').length
  const tools = installed.reduce((total, row) => total + row.tools, 0)

  return (
    <ControlPage
      className="capabilities-page"
      description={t('Local MCP servers Marvi can call as tools, installed or from the registry.')}
      title={t('MCP')}
    >
      <div className="capability-overview" aria-label={t('MCP summary')}>
        <div>
          <span>
            <Tr text={'Installed'} />
          </span>
          <strong>{installed.length}</strong>
        </div>
        <div>
          <span>
            <Tr text={'Connected'} />
          </span>
          <strong>{connected}</strong>
        </div>
        <div>
          <span>
            <Tr text={'Available tools'} />
          </span>
          <strong>{tools}</strong>
        </div>
        <div>
          <span>
            <Tr text={'Registry results'} />
          </span>
          <strong>{registry.length}</strong>
        </div>
      </div>
      <div className="capability-store-tabs" role="tablist" aria-label={t('MCP stores')}>
        {STORE_TABS.map((tab) => (
          <button
            aria-selected={storeTab === tab.key}
            className="capability-store-tab"
            key={tab.key}
            onClick={() => {
              setStoreTab(tab.key)
              if (tab.key === 'registry') {
                setRegistry([])
                setRegistryPage(0)
                setRegistryTotalPages(1)
              }
            }}
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
            aria-label={t('Search MCP servers')}
            className="capability-search"
            onChange={(event) => {
              setQuery(event.target.value)
              if (storeTab === 'registry') {
                setRegistry([])
                setRegistryPage(0)
                setRegistryTotalPages(1)
              }
            }}
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

        {!loaded || (storeTab === 'registry' && registryPage === 0) ? null : empty ? (
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
                    <strong>
                      <Tr text={'Installed servers'} />
                    </strong>
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
                          <TechnicalText>{row.id}</TechnicalText>
                        </div>
                        <ControlPill tone={row.status === 'connected' ? 'ready' : 'danger'}>
                          {row.status}
                        </ControlPill>
                      </header>
                      <p>
                        <Tr text={'Tools exposed to Marvi through this local server.'} />
                      </p>
                      <div className="capability-card-meta">
                        <span>
                          {row.tools} <Tr text={'tool'} before />
                          {row.tools === 1 ? '' : 's'}
                        </span>
                        <span>
                          <Tr text={'Installed'} />
                        </span>
                      </div>
                      <footer className="capability-card-actions">
                        <button
                          className="phase danger"
                          disabled={busy === row.id}
                          onClick={() => void remove(row.id)}
                          type="button"
                        >
                          <Trash2 aria-hidden="true" size={13} />{' '}
                          <Tr text={'Remove'} before after />
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
                    <strong>
                      <Tr text={'Registry catalog'} />
                    </strong>
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
                        <ControlPill>
                          <Tr text={'Registry'} />
                        </ControlPill>
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
                          <Tr text={'Review and install'} />
                        </button>
                      </footer>
                    </article>
                  ))}
                </div>
                <div className="capability-load-row">
                  <span>
                    {registryFiltered.length} <Tr text={'available from'} before after />
                    {registry.length} <Tr text={'loaded entries'} before after />
                  </span>
                  {registryPage < registryTotalPages ? (
                    <button
                      className="phase"
                      disabled={loadingRegistry}
                      onClick={() => void loadRegistry(query, registryPage + 1, true)}
                      type="button"
                    >
                      {loadingRegistry ? 'Loading…' : 'Load more servers'}
                    </button>
                  ) : (
                    <span>
                      <Tr text={'End of registry'} />
                    </span>
                  )}
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
