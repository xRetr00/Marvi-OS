import { describe, expect, it } from 'vitest'

import type {
  InstalledSkill,
  McpInstalledServer,
  McpRegistryServer,
  StoreSkill
} from '../../../../shared/runtime'
import {
  filterInstalledServers,
  filterInstalledSkills,
  filterRegistryServers,
  filterStoreSkills,
  matchesCapability,
  skillStoreSources
} from './capability-library'

const usage = { uses: 0, lastUsed: '', mine: false, pinned: false, state: 'active' as const }

describe('capability library filters', () => {
  it('matches case-insensitively across capability metadata', () => {
    expect(matchesCapability('POSTGRES', 'Database tools', 'PostgreSQL')).toBe(true)
    expect(matchesCapability('calendar', 'PDF', 'Documents')).toBe(false)
    expect(matchesCapability('  ', 'anything')).toBe(true)
  })

  it('searches installed skills and catalog skills beyond their display name', () => {
    const installed: InstalledSkill[] = [
      {
        name: 'research',
        description: 'Current sources',
        source: 'built-in',
        platforms: [],
        requires: [],
        applies: true,
        usage
      }
    ]
    const store: StoreSkill[] = [
      {
        name: 'deck-maker',
        description: 'Presentations',
        source: 'official',
        repo: 'openai/skills',
        path: 'slides',
        installed: false
      }
    ]

    expect(filterInstalledSkills(installed, 'source')).toHaveLength(1)
    expect(filterStoreSkills(store, 'openai')).toHaveLength(1)
    expect(skillStoreSources(store, ['curated/skills', 'openai/skills'])).toEqual([
      'curated/skills',
      'openai/skills'
    ])
  })

  it('keeps operational servers separate from registry discoveries', () => {
    const installed: McpInstalledServer[] = [
      { id: 'github-local', name: 'GitHub', status: 'connected', tools: 12, source: 'installed' }
    ]
    const registry: McpRegistryServer[] = [
      {
        qualifiedName: 'io.github/mcp',
        name: 'GitHub',
        description: 'Repositories',
        author: 'GitHub',
        source: 'registry'
      },
      {
        qualifiedName: 'io.postgres/mcp',
        name: 'PostgreSQL',
        description: 'Database queries',
        author: 'Community',
        source: 'registry'
      }
    ]

    expect(filterInstalledServers(installed, 'connected')).toHaveLength(1)
    expect(filterRegistryServers(registry, installed, '')).toEqual([registry[1]])
    expect(filterRegistryServers(registry, installed, 'database')).toEqual([registry[1]])
  })
})
