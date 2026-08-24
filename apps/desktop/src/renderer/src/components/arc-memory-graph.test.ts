import { describe, expect, it } from 'vitest'

import type { MemoryGraphPage } from '../../../shared/runtime'
import { memoryNodeColor, memoryNodeRadius, seedMemoryGraph } from './arc-memory-layout'

describe('ARC memory graph layout', () => {
  it('gives d3-force a deterministic, non-overlapping seed', () => {
    const graph: MemoryGraphPage = {
      mode: 'tree',
      nodes: [
        { id: 'arc:memory', kind: 'root', label: 'Memory' },
        { id: 'source:marvi', kind: 'source', label: 'marvi' },
        { id: 'memory:1', kind: 'summary', label: 'Prefers concise replies' }
      ],
      edges: [
        { id: 'a', source: 'arc:memory', target: 'source:marvi' },
        { id: 'b', source: 'source:marvi', target: 'memory:1' }
      ]
    }

    const first = seedMemoryGraph(graph)
    const second = seedMemoryGraph(graph)

    expect(first).toEqual(second)
    expect(first.find((node) => node.kind === 'root')).toMatchObject({ x: 0, y: 0 })
    expect(first.find((node) => node.id === 'memory:1')).not.toMatchObject({ x: 0, y: 0 })
    expect(memoryNodeRadius(graph.nodes[0])).toBeGreaterThan(memoryNodeRadius(graph.nodes[2]))
  })

  it('lays contact nodes without requiring a synthetic root', () => {
    const graph: MemoryGraphPage = {
      mode: 'contacts',
      nodes: [
        { id: 'entity:1', kind: 'contact', label: 'Sam' },
        { id: 'entity:2', kind: 'contact', label: 'Tiny Humans' }
      ],
      edges: [{ id: 'r:1', source: 'entity:1', target: 'entity:2', label: 'works at' }]
    }

    const points = seedMemoryGraph(graph)

    expect(points).toHaveLength(2)
    expect([points[0].x, points[0].y]).not.toEqual([points[1].x, points[1].y])
    expect(memoryNodeColor({ ...graph.nodes[0], trusted: false })).toBe(0xd86868)
  })
})
