import type { ChatPart, ChatWidgetPart } from '../../../../shared/runtime'

type Item = Record<string, string>

export function WidgetStack({ parts }: { parts: readonly ChatPart[] }): React.JSX.Element | null {
  const widgets = parts.filter((part): part is ChatWidgetPart => part.type === 'widget')
  const sources = parts.filter(
    (part): part is Extract<ChatPart, { type: 'source' }> => part.type === 'source'
  )
  if (!widgets.some((widget) => widget.kind === 'sources') && sources.length) {
    widgets.push({
      type: 'widget',
      id: 'legacy-sources',
      version: 1,
      kind: 'sources',
      title: 'Sources',
      status: 'complete',
      data: { items: sources }
    })
  }
  if (!widgets.length) return null
  return (
    <div className="chat-widgets">
      {widgets.map((widget) => (
        <Widget key={widget.id} widget={widget} />
      ))}
    </div>
  )
}

function Widget({ widget }: { widget: ChatWidgetPart }): React.JSX.Element {
  const rows = items(widget.data)
  return (
    <section className={`chat-widget chat-widget-${widget.kind}`} aria-label={widget.title}>
      <header>
        <span>{widget.kind.toUpperCase()}</span>
        <strong>{widget.title}</strong>
      </header>
      {widget.kind === 'table' ? <DataTable data={widget.data} /> : null}
      {widget.kind === 'sources' ? <Sources rows={rows} /> : null}
      {widget.kind === 'gallery' ? <Gallery rows={rows} /> : null}
      {widget.kind === 'weather' || widget.kind === 'document' ? (
        <Details data={widget.data} />
      ) : null}
      {['metrics', 'comparison', 'timeline', 'status'].includes(widget.kind) ? (
        <Rows rows={rows} />
      ) : null}
    </section>
  )
}

function Sources({ rows }: { rows: Item[] }): React.JSX.Element {
  return (
    <div className="chat-widget-sources">
      {rows.map((row, index) => (
        <a href={row.url} key={row.url} rel="noreferrer noopener" target="_blank">
          <span>{String(index + 1).padStart(2, '0')}</span>
          <strong>{row.title}</strong>
          <small>{row.snippet || host(row.url)}</small>
        </a>
      ))}
    </div>
  )
}

function Rows({ rows }: { rows: Item[] }): React.JSX.Element {
  return (
    <div className="chat-widget-rows">
      {rows.map((row, index) => (
        <div key={`${row.label}-${index}`}>
          <span>{row.at || row.label || String(index + 1).padStart(2, '0')}</span>
          <strong>{row.value || row.detail || row.status}</strong>
          {row.detail && row.value ? <small>{row.detail}</small> : null}
        </div>
      ))}
    </div>
  )
}

function DataTable({ data }: { data: Record<string, unknown> }): React.JSX.Element {
  const columns = strings(data.columns)
  const rows = Array.isArray(data.rows) ? data.rows.filter(Array.isArray).map(strings) : []
  return (
    <div className="chat-widget-table">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {columns.map((_, cell) => (
                <td key={cell}>{row[cell] || '—'}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Details({ data }: { data: Record<string, unknown> }): React.JSX.Element {
  const entries = Object.entries(data).filter(([, value]) => typeof value === 'string' && value)
  return (
    <dl className="chat-widget-details">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>
            {key === 'url' ? (
              <a href={String(value)} rel="noreferrer noopener" target="_blank">
                OPEN SOURCE ↗
              </a>
            ) : (
              String(value)
            )}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function Gallery({ rows }: { rows: Item[] }): React.JSX.Element {
  return (
    <div className="chat-widget-gallery">
      {rows.map((row, index) =>
        row.url ? (
          <figure key={`${row.url}-${index}`}>
            <img alt={row.alt || ''} src={row.url} />
            <figcaption>{row.alt || `IMAGE ${index + 1}`}</figcaption>
          </figure>
        ) : null
      )}
    </div>
  )
}

function items(data: Record<string, unknown>): Item[] {
  return Array.isArray(data.items)
    ? data.items.filter((row): row is Item => Boolean(row) && typeof row === 'object')
    : []
}
function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : []
}
function host(url: string): string {
  try {
    return new URL(url).hostname
  } catch {
    return 'source'
  }
}
