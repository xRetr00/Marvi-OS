import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link2 } from 'lucide-react'

import { ControlEmpty, ControlPage, ControlPill, ControlSection } from '../control-surface'
import {
  CONNECTOR_CATALOG,
  CONNECTOR_CATEGORY_LABELS,
  type ConnectorCategory,
  type ConnectorMeta
} from '../../lib/connectors/connectorCatalog'
import { ConnectorCard } from './ConnectorCard'
import { ConnectorConnectModal } from './ConnectorConnectModal'
import type { ConnectorRow } from '../../../../shared/runtime'

type Chip = 'all' | ConnectorCategory

const CHIPS: Chip[] = ['all', 'chat', 'productivity', 'tools', 'social', 'platform']

function chipLabel(chip: Chip): string {
  return chip === 'all' ? 'All' : CONNECTOR_CATEGORY_LABELS[chip]
}

/**
 * Capabilities > Connectors: an openhuman-shaped grid over Marvi's own
 * `/connectors` Gateway contract. The catalog (name, category, description)
 * ships with the renderer and paints on the first frame; `GET /connectors`
 * only ever overlays live status on top of it, and a 404 or offline Gateway
 * — the other side of this feature may not have landed yet — degrades to
 * every card reading "Not connected" rather than a blocked loading state.
 */
export function ConnectorsPanel(): React.JSX.Element {
  const [rows, setRows] = useState<ConnectorRow[]>([])
  const [available, setAvailable] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const [chip, setChip] = useState<Chip>('all')
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<ConnectorMeta | null>(null)

  const load = useCallback(async (): Promise<void> => {
    const next = await window.marvi?.getConnectors()
    setLoaded(true)
    if (!next) return
    setAvailable(next.available)
    setRows(next.connectors)
  }, [])

  useEffect(() => {
    let disposed = false
    const update = async (): Promise<void> => {
      if (!disposed) await load()
    }
    void update()
    const timer = setInterval(() => void update(), 15_000)
    return () => {
      disposed = true
      clearInterval(timer)
    }
  }, [load])

  const rowBySlug = useMemo(() => new Map(rows.map((row) => [row.slug, row])), [rows])

  const visible = CONNECTOR_CATALOG.filter((entry) => {
    if (chip !== 'all' && entry.category !== chip) return false
    const needle = query.trim().toLowerCase()
    if (!needle) return true
    return `${entry.name} ${entry.description}`.toLowerCase().includes(needle)
  })

  const connectedCount = rows.filter((row) => row.status === 'connected').length

  return (
    <ControlPage
      className="capabilities-page"
      description="Authorize third-party services so Marvi can read and act on your behalf."
      title="Connectors"
    >
      <ControlSection
        action={
          loaded ? (
            <ControlPill tone={connectedCount > 0 ? 'ready' : 'neutral'}>
              {connectedCount} connected
            </ControlPill>
          ) : undefined
        }
        icon={Link2}
        title="Connect a service"
      >
        <div className="capability-toolbar">
          <input
            aria-label="Search connectors"
            className="capability-search"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search connectors…"
            type="search"
            value={query}
          />
          <div className="capability-chips" role="group" aria-label="Filter by category">
            {CHIPS.map((option) => (
              <button
                aria-pressed={chip === option}
                className="capability-chip"
                key={option}
                onClick={() => setChip(option)}
                type="button"
              >
                {chipLabel(option)}
              </button>
            ))}
          </div>
        </div>

        {!available && loaded ? (
          <ControlEmpty
            description="The connector service is not configured on the Gateway yet. The catalog below still shows what's supported."
            icon={Link2}
            title="Connector service unavailable"
          />
        ) : null}

        {visible.length === 0 ? (
          <ControlEmpty
            description="Try a different search or category."
            title="No connectors found"
          />
        ) : (
          <div className="connector-grid">
            {visible.map((meta) => {
              const row = rowBySlug.get(meta.slug)
              return (
                <ConnectorCard
                  connections={row?.connections ?? 0}
                  key={meta.slug}
                  meta={meta}
                  onSelect={() => setOpen(meta)}
                  status={row?.status ?? 'disconnected'}
                />
              )
            })}
          </div>
        )}
      </ControlSection>

      {open ? (
        <ConnectorConnectModal
          meta={open}
          onChanged={() => void load()}
          onClose={() => setOpen(null)}
          row={rowBySlug.get(open.slug)}
        />
      ) : null}
    </ControlPage>
  )
}
