import { describe, expect, it } from 'vitest'
import type { MemoryEntry } from '../../../shared/runtime'
import { recentlyLearned } from './memory-health-utils'

const at = (hoursAgo: number): string => new Date(Date.now() - hoursAgo * 3_600_000).toISOString()
const entry = (id: number, source: string, hoursAgo: number): MemoryEntry => ({
  id,
  kind: 'semantic',
  subject: `s${id}`,
  body: 'b',
  source,
  trusted: true,
  at: at(hoursAgo)
})

describe('recently learned', () => {
  it('shows what she wrote down or worked out lately, newest first', () => {
    const found = recentlyLearned([
      entry(1, 'marvi', 30),
      entry(2, 'dreaming', 2),
      entry(3, 'import:shereef', 1),
      entry(4, 'composio:gmail', 1),
      entry(5, 'marvi', 24 * 5)
    ])
    expect(found.map((one) => one.id)).toEqual([2, 1])
  })
})
