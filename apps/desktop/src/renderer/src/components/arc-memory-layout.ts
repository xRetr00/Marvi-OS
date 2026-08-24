import type { MemoryGraphNode, MemoryGraphPage } from '../../../shared/runtime'

const WIDTH = 1000
const HEIGHT = 620

export interface GraphPoint extends MemoryGraphNode {
  x: number
  y: number
}

/** A stable radial seed keeps the graph readable before any interaction and
 * makes screenshots/tests deterministic. The renderer owns positions only;
 * Gateway remains the authority for nodes and edges. */
export function layoutMemoryGraph(graph: MemoryGraphPage): GraphPoint[] {
  if (graph.nodes.length === 0) return []
  const connected = new Map<string, string[]>()
  for (const edge of graph.edges) {
    connected.set(edge.source, [...(connected.get(edge.source) ?? []), edge.target])
    connected.set(edge.target, [...(connected.get(edge.target) ?? []), edge.source])
  }

  if (graph.mode === 'contacts') {
    return graph.nodes.map((node, index) => {
      const angle = (index / Math.max(graph.nodes.length, 1)) * Math.PI * 2 - Math.PI / 2
      const degree = connected.get(node.id)?.length ?? 0
      const radius = Math.max(150, 250 - degree * 9)
      return {
        ...node,
        x: WIDTH / 2 + Math.cos(angle) * radius,
        y: HEIGHT / 2 + Math.sin(angle) * radius * 0.72
      }
    })
  }

  const root = graph.nodes.find((node) => node.kind === 'root')
  const sources = graph.nodes.filter((node) => node.kind === 'source')
  const points = new Map<string, GraphPoint>()
  if (root) points.set(root.id, { ...root, x: WIDTH / 2, y: HEIGHT / 2 })
  sources.forEach((source, sourceIndex) => {
    const angle = (sourceIndex / Math.max(sources.length, 1)) * Math.PI * 2 - Math.PI / 2
    const sx = WIDTH / 2 + Math.cos(angle) * 205
    const sy = HEIGHT / 2 + Math.sin(angle) * 150
    points.set(source.id, { ...source, x: sx, y: sy })
    const children = graph.edges
      .filter((edge) => edge.source === source.id)
      .map((edge) => graph.nodes.find((node) => node.id === edge.target))
      .filter((node): node is MemoryGraphNode => Boolean(node))
    children.forEach((child, childIndex) => {
      const spread = Math.min(Math.PI * 1.25, 0.3 * Math.max(children.length - 1, 1))
      const childAngle =
        angle - spread / 2 + (childIndex / Math.max(children.length - 1, 1)) * spread
      const ring = 88 + Math.floor(childIndex / 12) * 32
      points.set(child.id, {
        ...child,
        x: sx + Math.cos(childAngle) * ring,
        y: sy + Math.sin(childAngle) * ring
      })
    })
  })
  graph.nodes.forEach((node, index) => {
    if (!points.has(node.id)) {
      const angle = index * 2.399963
      points.set(node.id, {
        ...node,
        x: WIDTH / 2 + Math.cos(angle) * 260,
        y: HEIGHT / 2 + Math.sin(angle) * 190
      })
    }
  })
  return graph.nodes.map((node) => points.get(node.id)!)
}
