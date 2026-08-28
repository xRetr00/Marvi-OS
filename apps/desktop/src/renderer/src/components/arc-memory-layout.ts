import type { SimulationNodeDatum } from 'd3-force'

import type { MemoryGraphNode, MemoryGraphPage } from '../../../shared/runtime'

export interface ForceGraphNode extends MemoryGraphNode, SimulationNodeDatum {
  x: number
  y: number
  /** How many edges touch it. Obsidian sizes a node by this, and it is what
   * turns a wall of identical dots into something with a shape you can read. */
  degree: number
}

/**
 * How the graph is laid out and drawn.
 *
 * The settings are Obsidian's, named the way Obsidian names them, because they
 * are the right four knobs and people already know what they do: centre force
 * is how compact the whole thing is, repel is how hard nodes push each other
 * apart, link force is how tight the rubber band is, and link distance is how
 * long it is at rest.
 */
export interface GraphSettings {
  centerForce: number
  repelForce: number
  linkForce: number
  linkDistance: number
  nodeSize: number
  linkThickness: number
  /** Below this zoom, labels fade out. Obsidian calls it the text fade
   * threshold, and it is the setting that makes a large graph readable: every
   * label at once is noise, and no labels at all is a starfield. */
  textFade: number
  showArrows: boolean
  /** Nodes with no edges. Worth hiding on a big graph and worth seeing on a
   * small one, which is why it is a switch rather than a decision. */
  showOrphans: boolean
}

export const DEFAULT_GRAPH_SETTINGS: GraphSettings = {
  centerForce: 0.055,
  repelForce: 95,
  linkForce: 0.42,
  linkDistance: 52,
  nodeSize: 1,
  linkThickness: 0.85,
  textFade: 0.75,
  showArrows: false,
  showOrphans: true
}

/** Deterministic phyllotaxis seeds. d3-force owns the final layout; the seed
 * merely makes first paint and tests stable while the graph warms up. */
export function seedMemoryGraph(graph: MemoryGraphPage): ForceGraphNode[] {
  const degree = new Map<string, number>()
  for (const edge of graph.edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1)
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1)
  }
  return graph.nodes.map((node, index) => {
    const radius = 14 * Math.sqrt(index)
    const angle = index * Math.PI * (3 - Math.sqrt(5))
    return {
      ...node,
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
      degree: degree.get(node.id) ?? 0
    }
  })
}

/**
 * How big a node is drawn.
 *
 * By degree, the way Obsidian does it, with the kind only setting the floor.
 * Every node was one of four fixed sizes, so a hub joining forty memories drew
 * the same as a leaf and the picture said nothing about the shape of what
 * Marvi knows. Square root rather than linear: a node with a hundred edges is
 * more important than one with four, not twenty-five times the area.
 */
export function memoryNodeRadius(node: MemoryGraphNode, settings?: GraphSettings): number {
  const base =
    node.kind === 'root'
      ? 7
      : node.kind === 'source'
        ? 5
        : node.kind === 'summary' || node.kind === 'contact'
          ? 4
          : 3
  const degree = (node as ForceGraphNode).degree ?? 0
  return (base + Math.sqrt(degree) * 1.6) * (settings?.nodeSize ?? 1)
}

export function memoryNodeColor(node: MemoryGraphNode): number {
  if (node.trusted === false) return 0xd86868
  if (node.kind === 'root') return 0x4ba6df
  if (node.kind === 'source') return 0xe8eaed
  if (node.kind === 'summary' || node.kind === 'contact') return 0xaeb4bd
  return 0x626974
}

/** Which nodes are one hop from this one, plus itself.
 *
 * Hovering a node in Obsidian highlights what it connects to and dims the
 * rest, which is the single interaction that makes a hairball legible: 152
 * nodes around one hub tells you nothing until you can ask "what does *this*
 * touch". */
export function neighbourhood(graph: MemoryGraphPage, id: string): Set<string> {
  const near = new Set<string>([id])
  for (const edge of graph.edges) {
    if (edge.source === id) near.add(edge.target)
    else if (edge.target === id) near.add(edge.source)
  }
  return near
}
