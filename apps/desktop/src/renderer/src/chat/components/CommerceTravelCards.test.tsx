import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ChatWidgetPart } from '../../../../shared/runtime'
import { WidgetStack } from './WidgetStack'

const widget = (kind: ChatWidgetPart['kind'], data: Record<string, unknown>): ChatWidgetPart => ({
  type: 'widget',
  id: kind,
  version: 1,
  kind,
  title: kind,
  status: 'complete',
  data
})

describe('commerce and travel cards', () => {
  it.each([
    [
      'receipt',
      { merchant: 'Shop', total: '$12', items: [{ name: 'Cable', price: '$12' }] },
      'Cable'
    ],
    ['cart', { total: '$12', items: [{ name: 'Cable', price: '$12' }] }, 'Cable'],
    ['order_status', { order_id: 'A123', status: 'In transit' }, 'In transit'],
    ['booking', { venue: 'Cafe', date: 'Oct 1', time: '19:00' }, 'Cafe'],
    ['stays', { name: 'Riverside Loft', location: 'Paris' }, 'Riverside Loft'],
    [
      'flight_tracker',
      { flight: 'AB123', origin: 'IST', destination: 'LHR', status: 'On time' },
      'AB123'
    ]
  ] as const)('renders %s as a display-only card', (kind, data, visible) => {
    const html = renderToStaticMarkup(<WidgetStack parts={[widget(kind, data)]} />)
    expect(html).toContain(visible)
    expect(html).toContain('SUPPLIED DETAILS')
    expect(html).not.toContain('<button')
  })

  it('only links to public HTTP sources', () => {
    const base = { venue: 'Cafe', date: 'Oct 1', time: '19:00' }
    expect(
      renderToStaticMarkup(
        <WidgetStack
          parts={[widget('booking', { ...base, source_url: 'https://example.com/booking' })]}
        />
      )
    ).toContain('https://example.com/booking')
    expect(
      renderToStaticMarkup(
        <WidgetStack parts={[widget('booking', { ...base, source_url: 'javascript:alert(1)' })]} />
      )
    ).not.toContain('href=')
  })
})
