import { describe, expect, it } from 'vitest'

import {
  isSafeConnectUrl,
  normaliseConnectorRow,
  normaliseConnectorsPage
} from './connector-runtime'

describe('connector lifecycle bridge', () => {
  it('only opens https authorization links', () => {
    expect(isSafeConnectUrl('https://connect.example.com/link/abc')).toBe(true)
    expect(isSafeConnectUrl('http://connect.example.com/link/abc')).toBe(false)
    expect(isSafeConnectUrl('javascript:alert(1)')).toBe(false)
    expect(isSafeConnectUrl('not a url')).toBe(false)
  })

  it('normalises the Gateway snake_case contract into renderer-owned fields', () => {
    const row = normaliseConnectorRow({
      slug: 'gmail',
      name: 'Gmail',
      status: 'connected',
      connection_id: 'conn_1',
      scope: 'write',
      connections: 2,
      error: ''
    })

    expect(row).toMatchObject({
      slug: 'gmail',
      name: 'Gmail',
      status: 'connected',
      connectionId: 'conn_1',
      scope: 'write',
      connections: 2
    })
  })

  it('falls back to safe defaults for an unrecognised status or missing scope', () => {
    const row = normaliseConnectorRow({ slug: 'slack', status: 'bogus' })
    expect(row.status).toBe('disconnected')
    expect(row.scope).toBe('read')
    expect(row.connections).toBe(0)
  })

  it('reports unavailable rather than throwing when the Gateway body is empty', () => {
    const page = normaliseConnectorsPage(null)
    expect(page).toEqual({ available: false, connectors: [] })
  })

  it('maps every connector row in a full page response', () => {
    const page = normaliseConnectorsPage({
      available: true,
      connectors: [
        { slug: 'github', name: 'GitHub', status: 'expired', connection_id: 'c1', scope: 'read' },
        { slug: 'notion', name: 'Notion', status: 'preview', connection_id: '', scope: 'read' }
      ]
    })

    expect(page.available).toBe(true)
    expect(page.connectors).toHaveLength(2)
    expect(page.connectors[0]).toMatchObject({ slug: 'github', status: 'expired' })
    expect(page.connectors[1]).toMatchObject({ slug: 'notion', status: 'preview' })
  })
})
