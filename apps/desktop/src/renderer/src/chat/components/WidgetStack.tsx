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
  if (widget.kind === 'sources') return <Sources rows={rows} title={widget.title} />
  if (widget.kind === 'table') return <DataTable data={widget.data} title={widget.title} />
  if (widget.kind === 'gallery') return <Gallery rows={rows} title={widget.title} />
  if (widget.kind === 'comparison') return <Comparison rows={rows} title={widget.title} />
  if (widget.kind === 'timeline') return <Timeline rows={rows} title={widget.title} />
  if (widget.kind === 'metrics') return <Metrics rows={rows} title={widget.title} />
  if (widget.kind === 'weather' || widget.kind === 'document') {
    return <Details data={widget.data} title={widget.title} />
  }
  return <Status rows={rows} title={widget.title} />
}

function CardTitle({ children }: { children: string }): React.JSX.Element {
  return <h3 className="chat-card-title">{children}</h3>
}

function Sources({ rows, title }: { rows: Item[]; title: string }): React.JSX.Element {
  return (
    <details className="chat-sources">
      <summary>
        <span className="chat-sources-stack" aria-hidden="true">
          {rows.slice(0, 3).map((row, index) => (
            <span key={`${row.url}-${index}`}>{host(row.url).slice(0, 1).toUpperCase()}</span>
          ))}
        </span>
        <strong>{title}</strong>
        <span>{rows.length}</span>
        <span className="chat-sources-chevron" aria-hidden="true">
          ⌄
        </span>
      </summary>
      <div className="chat-source-grid">
        {rows.map((row, index) => (
          <a href={row.url} key={`${row.url}-${index}`} rel="noreferrer noopener" target="_blank">
            <span className="chat-source-index">{String(index + 1).padStart(2, '0')}</span>
            <strong>{row.title || host(row.url)}</strong>
            <small>{row.snippet || host(row.url)}</small>
            <span className="chat-source-host">{host(row.url)} ↗</span>
          </a>
        ))}
      </div>
    </details>
  )
}

function Metrics({ rows, title }: { rows: Item[]; title: string }): React.JSX.Element {
  return (
    <section className="chat-card chat-metrics" aria-label={title}>
      <CardTitle>{title}</CardTitle>
      <div>
        {rows.map((row, index) => (
          <div className="chat-metric" key={`${row.label}-${index}`}>
            <span>{row.label || String(index + 1).padStart(2, '0')}</span>
            <strong>{row.value || row.status || '—'}</strong>
            {row.detail ? <small>{row.detail}</small> : null}
          </div>
        ))}
      </div>
    </section>
  )
}

function Comparison({ rows, title }: { rows: Item[]; title: string }): React.JSX.Element {
  return (
    <section className="chat-card chat-comparison" aria-label={title}>
      <CardTitle>{title}</CardTitle>
      <div className="chat-comparison-options">
        {rows.map((row, index) => {
          const recommended = /recommend|best|pick/i.test(
            `${row.value} ${row.detail} ${row.status}`
          )
          return (
            <div
              className={recommended ? 'chat-option recommended' : 'chat-option'}
              key={`${row.label}-${index}`}
            >
              <span>{row.label || `Option ${index + 1}`}</span>
              {recommended ? <em>PICK</em> : null}
              <strong>{row.value || row.status || '—'}</strong>
              {row.detail ? <small>{row.detail}</small> : null}
            </div>
          )
        })}
      </div>
    </section>
  )
}

function Timeline({ rows, title }: { rows: Item[]; title: string }): React.JSX.Element {
  return (
    <section className="chat-card chat-timeline" aria-label={title}>
      <CardTitle>{title}</CardTitle>
      <ol>
        {rows.map((row, index) => (
          <li key={`${row.at}-${row.label}-${index}`}>
            <time>{row.at || String(index + 1).padStart(2, '0')}</time>
            <span aria-hidden="true" />
            <div>
              <strong>{row.label || row.value || row.status}</strong>
              {row.detail || (row.label && row.value) ? (
                <small>{row.detail || row.value}</small>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}

function Status({ rows, title }: { rows: Item[]; title: string }): React.JSX.Element {
  return (
    <section className="chat-card chat-status" aria-label={title}>
      <CardTitle>{title}</CardTitle>
      <div>
        {rows.map((row, index) => (
          <div className="chat-status-row" key={`${row.label}-${index}`}>
            <span>{row.label || String(index + 1).padStart(2, '0')}</span>
            <strong>{row.value || row.detail || row.status || '—'}</strong>
          </div>
        ))}
      </div>
    </section>
  )
}

function DataTable({
  data,
  title
}: {
  data: Record<string, unknown>
  title: string
}): React.JSX.Element {
  const columns = strings(data.columns)
  const rows = Array.isArray(data.rows) ? data.rows.filter(Array.isArray).map(strings) : []
  return (
    <section className="chat-card chat-data-card" aria-label={title}>
      <CardTitle>{title}</CardTitle>
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
    </section>
  )
}

function Details({
  data,
  title
}: {
  data: Record<string, unknown>
  title: string
}): React.JSX.Element {
  const entries = Object.entries(data).filter(
    ([key, value]) => key !== 'items' && typeof value === 'string' && value
  )
  return (
    <section className="chat-card chat-details" aria-label={title}>
      <CardTitle>{title}</CardTitle>
      <dl>
        {entries.map(([key, value]) => (
          <div key={key}>
            <dt>{key.replaceAll('_', ' ')}</dt>
            <dd>
              {key === 'url' ? (
                <a href={String(value)} rel="noreferrer noopener" target="_blank">
                  Open source ↗
                </a>
              ) : (
                String(value)
              )}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function Gallery({ rows, title }: { rows: Item[]; title: string }): React.JSX.Element {
  return (
    <section className="chat-card chat-gallery-card" aria-label={title}>
      <CardTitle>{title}</CardTitle>
      <div className="chat-widget-gallery">
        {rows.map((row, index) =>
          row.url ? (
            <figure key={`${row.url}-${index}`}>
              <img alt={row.alt || ''} src={row.url} />
              <figcaption>{row.alt || `Image ${index + 1}`}</figcaption>
            </figure>
          ) : null
        )}
      </div>
    </section>
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
