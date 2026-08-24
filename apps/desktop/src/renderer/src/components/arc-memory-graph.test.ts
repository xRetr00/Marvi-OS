import { describe, expect, it } from 'vitest'

import type { MemoryGraphPage } from '../../../shared/runtime'
import { layoutMemoryGraph } from './arc-memory-layout'

describe('ARC memory graph layout', () => {
  it('anchors the root and groups a memory around its source', () => {
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

    const first = layoutMemoryGraph(graph)
    const second = layoutMemoryGraph(graph)

    expect(first).toEqual(second)
    expect(first.find((node) => node.kind === 'root')).toMatchObject({ x: 500, y: 310 })
    expect(first.find((node) => node.id === 'memory:1')).not.toMatchObject({ x: 500, y: 310 })
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

    const points = layoutMemoryGraph(graph)

    expect(points).toHaveLength(2)
    expect([points[0].x, points[0].y]).not.toEqual([points[1].x, points[1].y])
  })
})
