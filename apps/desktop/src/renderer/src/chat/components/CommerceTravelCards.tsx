import { t } from '../../store/locale'
import { Tr } from '../../store/locale'
import type { ChatWidgetPart } from '../../../../shared/runtime'

type Data = Record<string, unknown>
const origin = (tool?: string): string => {
  if (tool === 'account_tool_execute') return 'CONNECTED ACCOUNT'
  if (tool?.startsWith('browser_')) return 'BROWSER RESULT'
  if (tool?.startsWith('web_')) return 'WEB RESULT'
  return tool ? 'TOOL RESULT' : 'SUPPLIED DETAILS'
}
const value = (data: Data, key: string): string =>
  typeof data[key] === 'string' ? (data[key] as string) : ''
const list = (data: Data, key: string): Data[] =>
  Array.isArray(data[key])
    ? (data[key] as unknown[]).filter(
        (item): item is Data => !!item && typeof item === 'object' && !Array.isArray(item)
      )
    : []

function source(url: string): React.JSX.Element | null {
  try {
    const parsed = new URL(url)
    if (
      !['https:', 'http:'].includes(parsed.protocol) ||
      parsed.username ||
      !parsed.hostname ||
      /^(localhost|127\.|10\.|192\.168\.)/.test(parsed.hostname)
    )
      return null
    return (
      <a href={parsed.href} rel="noopener noreferrer" target="_blank">
        <Tr text={'View source ↗'} />
      </a>
    )
  } catch {
    return null
  }
}

function Field({ label, value: text }: { label: string; value: string }): React.JSX.Element | null {
  if (!text) return null
  return (
    <div className="chat-transaction-field">
      <dt>{label}</dt>
      <dd>{text}</dd>
    </div>
  )
}

function Card({
  widget,
  children
}: {
  widget: ChatWidgetPart
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <section aria-label={widget.title} className="chat-widget-flat chat-transaction-card">
      <div className="chat-transaction-head">
        <span className="chat-widget-label">{widget.title}</span>
        <span className="chat-transaction-origin">{origin(widget.provenance?.tool)}</span>
      </div>
      {children}
      {source(value(widget.data, 'source_url'))}
    </section>
  )
}

function LineItems({ data }: { data: Data }): React.JSX.Element {
  return (
    <ul className="chat-transaction-items">
      {list(data, 'items').map((item, index) => (
        <li key={index}>
          <span>
            {value(item, 'name')}
            <small>{value(item, 'quantity') ? ` × ${value(item, 'quantity')}` : ''}</small>
          </span>
          <strong>{value(item, 'price')}</strong>
        </li>
      ))}
    </ul>
  )
}

export function CommerceTravelCard({ widget }: { widget: ChatWidgetPart }): React.JSX.Element {
  const data = widget.data
  if (widget.kind === 'receipt' || widget.kind === 'cart')
    return (
      <Card widget={widget}>
        <strong className="chat-transaction-title">
          {value(data, 'merchant') ||
            (widget.kind === 'cart' ? 'Shopping cart' : 'Purchase receipt')}
        </strong>
        <LineItems data={data} />
        <dl className="chat-transaction-facts">
          <Field label={t('Subtotal')} value={value(data, 'subtotal')} />
          <Field label={t('Tax')} value={value(data, 'tax')} />
          <Field label={t('Total')} value={value(data, 'total')} />
          <Field label={t('Order')} value={value(data, 'order_id')} />
          <Field label={t('Date')} value={value(data, 'date')} />
          <Field label={t('Delivery')} value={value(data, 'delivery')} />
        </dl>
      </Card>
    )
  if (widget.kind === 'order_status')
    return (
      <Card widget={widget}>
        <strong className="chat-transaction-title">{value(data, 'status')}</strong>
        <dl className="chat-transaction-facts">
          <Field label={t('Order')} value={value(data, 'order_id')} />
          <Field label={t('Merchant')} value={value(data, 'merchant')} />
          <Field label={t('Expected')} value={value(data, 'eta')} />
          <Field label={t('Updated')} value={value(data, 'updated_at')} />
        </dl>
        <ol className="chat-transaction-events">
          {list(data, 'events').map((event, index) => (
            <li key={index}>
              <time>{value(event, 'at')}</time>
              <span>{value(event, 'label')}</span>
              <small>{value(event, 'detail')}</small>
            </li>
          ))}
        </ol>
      </Card>
    )
  if (widget.kind === 'booking')
    return (
      <Card widget={widget}>
        <strong className="chat-transaction-title">{value(data, 'venue')}</strong>
        <dl className="chat-transaction-facts">
          <Field label={t('Date')} value={value(data, 'date')} />
          <Field label={t('Time')} value={value(data, 'time')} />
          <Field label={t('Party')} value={value(data, 'party_size')} />
          <Field label={t('Status')} value={value(data, 'status')} />
          <Field label={t('Reference')} value={value(data, 'reference')} />
          <Field label={t('Address')} value={value(data, 'address')} />
        </dl>
      </Card>
    )
  if (widget.kind === 'stays')
    return (
      <Card widget={widget}>
        <strong className="chat-transaction-title">{value(data, 'name')}</strong>
        <p className="chat-transaction-subtitle">{value(data, 'location')}</p>
        <dl className="chat-transaction-facts">
          <Field label={t('Dates')} value={value(data, 'dates')} />
          <Field label={t('Price')} value={value(data, 'price')} />
          <Field label={t('Rating')} value={value(data, 'rating')} />
        </dl>
        {value(data, 'detail') ? (
          <p className="chat-transaction-subtitle">{value(data, 'detail')}</p>
        ) : null}
      </Card>
    )
  return (
    <Card widget={widget}>
      <strong className="chat-transaction-title">
        {value(data, 'flight')} · {value(data, 'status')}
      </strong>
      <p className="chat-flight-route">
        <span>{value(data, 'origin')}</span>
        <span aria-hidden="true">→</span>
        <span>{value(data, 'destination')}</span>
      </p>
      <dl className="chat-transaction-facts">
        <Field label={t('Airline')} value={value(data, 'airline')} />
        <Field label={t('Departure')} value={value(data, 'departure')} />
        <Field label={t('Arrival')} value={value(data, 'arrival')} />
        <Field label={t('Gate')} value={value(data, 'gate')} />
        <Field label={t('Terminal')} value={value(data, 'terminal')} />
        <Field label={t('Updated')} value={value(data, 'updated_at')} />
      </dl>
    </Card>
  )
}
