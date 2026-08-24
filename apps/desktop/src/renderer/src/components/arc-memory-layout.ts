import type { SimulationNodeDatum } from 'd3-force'

import type { MemoryGraphNode, MemoryGraphPage } from '../../../shared/runtime'

export interface ForceGraphNode extends MemoryGraphNode, SimulationNodeDatum {
  x: number
  y: number
}

/** Deterministic phyllotaxis seeds. d3-force owns the final layout; the seed
 * merely makes first paint and tests stable while the graph warms up. */
export function seedMemoryGraph(graph: MemoryGraphPage): ForceGraphNode[] {
  return graph.nodes.map((node, index) => {
    const radius = 14 * Math.sqrt(index)
    const angle = index * Math.PI * (3 - Math.sqrt(5))
    return { ...node, x: Math.cos(angle) * radius, y: Math.sin(angle) * radius }
  })
}

export function memoryNodeRadius(node: MemoryGraphNode): number {
  if (node.kind === 'root') return 8
  if (node.kind === 'source') return 6
  if (node.kind === 'summary' || node.kind === 'contact') return 4.5
  return 3
}

export function memoryNodeColor(node: MemoryGraphNode): number {
  if (node.trusted === false) return 0xd86868
  if (node.kind === 'root') return 0x4ba6df
  if (node.kind === 'source') return 0xe8eaed
  if (node.kind === 'summary' || node.kind === 'contact') return 0xaeb4bd
  return 0x626974
}
