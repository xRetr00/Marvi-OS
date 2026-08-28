import { describe, expect, it } from 'vitest'

import {
  CONNECTOR_CATALOG,
  CONNECTOR_CATEGORY_LABELS,
  connectorMeta,
  connectorMonogram
} from './connectorCatalog'

describe('connector catalog', () => {
  it('has no duplicate slugs, since the slug is the join key against live status', () => {
    const slugs = CONNECTOR_CATALOG.map((entry) => entry.slug)
    expect(new Set(slugs).size).toBe(slugs.length)
  })

  it('assigns every entry a category with a filter-chip label', () => {
    for (const entry of CONNECTOR_CATALOG) {
      expect(CONNECTOR_CATEGORY_LABELS[entry.category]).toBeTruthy()
    }
  })

  it('looks up metadata by slug', () => {
    expect(connectorMeta('gmail')?.name).toBe('Gmail')
    expect(connectorMeta('not-a-real-connector')).toBeUndefined()
  })

  it('derives a two-letter monogram from one or many words', () => {
    expect(connectorMonogram('Slack')).toBe('SL')
    expect(connectorMonogram('Google Drive')).toBe('GD')
    expect(connectorMonogram('')).toBe('??')
  })
})
