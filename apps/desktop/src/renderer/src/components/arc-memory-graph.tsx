import { useCallback, useEffect, useRef, useState } from 'react'
import 'pixi.js/unsafe-eval'
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationLinkDatum
} from 'd3-force'
import { Application, Container, Graphics, Text, type FederatedPointerEvent } from 'pixi.js'
import { RotateCcw } from 'lucide-react'

import type { MemoryGraphNode, MemoryGraphPage } from '../../../shared/runtime'
import {
  memoryNodeColor,
  memoryNodeRadius,
  seedMemoryGraph,
  type ForceGraphNode
} from './arc-memory-layout'

interface ArcMemoryGraphProps {
  graph: MemoryGraphPage
  loading?: boolean
}

interface ForceLink extends SimulationLinkDatum<ForceGraphNode> {
  id: string
}

const MIN_ZOOM = 0.18
const MAX_ZOOM = 5

function shortLabel(label: string): string {
  return label.length > 28 ? `${label.slice(0, 27)}…` : label
}

function GraphCanvas({
  graph,
  resetEpoch,
  onHover
}: {
  graph: MemoryGraphPage
  resetEpoch: number
  onHover: (node: MemoryGraphNode | null) => void
}): React.JSX.Element {
  const hostRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    let disposed = false
    let cleanup: (() => void) | undefined

    void (async () => {
      const app = new Application()
      await app.init({
        resizeTo: host,
        antialias: true,
        backgroundAlpha: 0,
        preference: 'webgl'
      })
      if (disposed) {
        app.destroy(true)
        return
      }

      app.canvas.setAttribute('aria-label', 'Interactive ARC memory graph')
      app.canvas.setAttribute('data-testid', 'arc-memory-graph')
      app.canvas.setAttribute('role', 'img')
      host.appendChild(app.canvas)

      const world = new Container()
      const edges = new Graphics()
      const nodesLayer = new Container()
      const labelsLayer = new Container()
      world.addChild(edges, nodesLayer, labelsLayer)
      app.stage.addChild(world)

      const nodes = seedMemoryGraph(graph)
      const byId = new Map(nodes.map((node) => [node.id, node]))
      const links: ForceLink[] = graph.edges
        .filter((edge) => byId.has(edge.source) && byId.has(edge.target))
        .map((edge) => ({ id: edge.id, source: edge.source, target: edge.target }))
      const glyphs = new Map<string, Graphics>()
      const labels = new Map<string, Text>()

      for (const node of nodes) {
        const radius = memoryNodeRadius(node)
        const glyph = new Graphics()
          .circle(0, 0, radius + 2.4)
          .fill({ color: memoryNodeColor(node), alpha: 0.12 })
          .circle(0, 0, radius)
          .fill({ color: memoryNodeColor(node), alpha: 0.96 })
        glyph.eventMode = 'static'
        glyph.cursor = 'pointer'
        glyphs.set(node.id, glyph)
        nodesLayer.addChild(glyph)

        const label = new Text({
          text: shortLabel(node.label),
          resolution: Math.max(2, window.devicePixelRatio),
          style: {
            fill: 0xc7cbd1,
            fontFamily: 'JetBrains Mono, monospace',
            fontSize: 10,
            fontWeight: '500'
          }
        })
        label.anchor.set(0.5, 0)
        label.visible = node.kind === 'root' || node.kind === 'source'
        labels.set(node.id, label)
        labelsLayer.addChild(label)

        glyph.on('pointerover', () => {
          label.visible = true
          glyph.scale.set(1.35)
          onHover(node)
        })
        glyph.on('pointerout', () => {
          label.visible = node.kind === 'root' || node.kind === 'source'
          glyph.scale.set(1)
          onHover(null)
        })
      }

      const draw = (): void => {
        edges.clear()
        for (const link of links) {
          const source =
            typeof link.source === 'object' ? link.source : byId.get(String(link.source))
          const target =
            typeof link.target === 'object' ? link.target : byId.get(String(link.target))
          if (!source || !target) continue
          edges.moveTo(source.x, source.y).lineTo(target.x, target.y)
        }
        edges.stroke({ color: 0x69717b, alpha: 0.48, width: 0.85 })
        for (const node of nodes) {
          glyphs.get(node.id)?.position.set(node.x, node.y)
          labels.get(node.id)?.position.set(node.x, node.y + memoryNodeRadius(node) + 7)
        }
      }

      const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      const simulation = forceSimulation(nodes)
        .force(
          'links',
          forceLink<ForceGraphNode, ForceLink>(links)
            .id((node) => node.id)
            .distance(graph.mode === 'contacts' ? 58 : 48)
            .strength(0.42)
        )
        .force('charge', forceManyBody().strength(-95).distanceMax(520).theta(0.9))
        .force('center', forceCenter(0, 0).strength(0.055))
        .force(
          'collide',
          forceCollide<ForceGraphNode>().radius((node) => memoryNodeRadius(node) + 9)
        )
        .velocityDecay(0.38)
        .alphaDecay(0.028)
        .on('tick', draw)

      if (reducedMotion) {
        simulation.stop()
        for (let index = 0; index < 180; index += 1) simulation.tick()
        draw()
      }

      const fit = (): void => {
        const bounds = nodes.reduce(
          (box, node) => ({
            minX: Math.min(box.minX, node.x),
            minY: Math.min(box.minY, node.y),
            maxX: Math.max(box.maxX, node.x),
            maxY: Math.max(box.maxY, node.y)
          }),
          { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity }
        )
        const width = Math.max(180, bounds.maxX - bounds.minX)
        const height = Math.max(180, bounds.maxY - bounds.minY)
        const scale = Math.min(
          2.2,
          Math.max(MIN_ZOOM, Math.min(host.clientWidth / width, host.clientHeight / height) * 0.78)
        )
        world.scale.set(scale)
        world.position.set(
          host.clientWidth / 2 - ((bounds.minX + bounds.maxX) / 2) * scale,
          host.clientHeight / 2 - ((bounds.minY + bounds.maxY) / 2) * scale
        )
      }
      fit()
      const fitTimer = window.setTimeout(fit, reducedMotion ? 0 : 900)

      let panning = false
      let dragNode: ForceGraphNode | null = null
      let lastX = 0
      let lastY = 0
      const toWorld = (event: PointerEvent): { x: number; y: number } => {
        const rect = app.canvas.getBoundingClientRect()
        return {
          x: (event.clientX - rect.left - world.position.x) / world.scale.x,
          y: (event.clientY - rect.top - world.position.y) / world.scale.y
        }
      }
      const pointerMove = (event: PointerEvent): void => {
        if (dragNode) {
          const point = toWorld(event)
          dragNode.fx = point.x
          dragNode.fy = point.y
          simulation.alphaTarget(0.22).restart()
          return
        }
        if (!panning) return
        world.position.x += event.clientX - lastX
        world.position.y += event.clientY - lastY
        lastX = event.clientX
        lastY = event.clientY
      }
      const pointerUp = (): void => {
        panning = false
        if (dragNode) {
          dragNode.fx = null
          dragNode.fy = null
          dragNode = null
          simulation.alphaTarget(0)
        }
      }
      const pointerDown = (event: PointerEvent): void => {
        if (event.button !== 0) return
        panning = true
        lastX = event.clientX
        lastY = event.clientY
      }
      const wheel = (event: WheelEvent): void => {
        event.preventDefault()
        const rect = app.canvas.getBoundingClientRect()
        const x = event.clientX - rect.left
        const y = event.clientY - rect.top
        const beforeX = (x - world.position.x) / world.scale.x
        const beforeY = (y - world.position.y) / world.scale.y
        const scale = Math.min(
          MAX_ZOOM,
          Math.max(MIN_ZOOM, world.scale.x * Math.exp(-event.deltaY * 0.0015))
        )
        world.scale.set(scale)
        world.position.set(x - beforeX * scale, y - beforeY * scale)
      }
      for (const node of nodes) {
        glyphs.get(node.id)?.on('pointerdown', (event: FederatedPointerEvent) => {
          event.stopPropagation()
          dragNode = node
          node.fx = node.x
          node.fy = node.y
        })
      }
      app.canvas.addEventListener('pointerdown', pointerDown)
      app.canvas.addEventListener('wheel', wheel, { passive: false })
      window.addEventListener('pointermove', pointerMove)
      window.addEventListener('pointerup', pointerUp)

      cleanup = () => {
        window.clearTimeout(fitTimer)
        simulation.stop()
        app.canvas.removeEventListener('pointerdown', pointerDown)
        app.canvas.removeEventListener('wheel', wheel)
        window.removeEventListener('pointermove', pointerMove)
        window.removeEventListener('pointerup', pointerUp)
        app.destroy(true, { children: true })
      }
    })().catch((error: unknown) => {
      if (disposed) return
      host.textContent = `GRAPH RENDERER UNAVAILABLE · ${error instanceof Error ? error.message : String(error)}`
      host.classList.add('arc-graph-render-error')
    })

    return () => {
      disposed = true
      cleanup?.()
    }
  }, [graph, onHover, resetEpoch])

  return <div className="arc-graph-canvas" ref={hostRef} />
}

export function ArcMemoryGraph({ graph, loading = false }: ArcMemoryGraphProps): React.JSX.Element {
  const [hovered, setHovered] = useState<MemoryGraphNode | null>(null)
  const [resetEpoch, setResetEpoch] = useState(0)
  const onHover = useCallback((node: MemoryGraphNode | null) => setHovered(node), [])

  if (loading) return <div className="arc-graph-empty">BUILDING ARC GRAPH…</div>
  if (graph.nodes.length === 0) {
    return (
      <div className="arc-graph-empty">
        <span>NO GRAPH YET</span>
        <small>Memories and explicit relationships will form the graph as Marvi learns.</small>
      </div>
    )
  }

  const legend =
    graph.mode === 'tree'
      ? [
          ['ROOT', 'root'],
          ['SOURCE', 'source'],
          ['FACT', 'summary'],
          ['EPISODE', 'chunk']
        ]
      : [
          ['ENTITY', 'contact'],
          ['UNTRUSTED', 'untrusted']
        ]

  return (
    <div className="arc-graph-frame" onMouseLeave={() => setHovered(null)}>
      <header className="arc-graph-header">
        <div className="arc-graph-counts">
          <span>{graph.nodes.length} NODES</span>
          <i>·</i>
          <span>{graph.edges.length} LINKS</span>
        </div>
        <div className="arc-graph-legend" aria-label="Graph legend">
          {legend.map(([label, kind]) => (
            <span key={label}>
              <i className={`arc-graph-key arc-graph-node-${kind}`} /> {label}
            </span>
          ))}
          <button type="button" onClick={() => setResetEpoch((value) => value + 1)}>
            <RotateCcw aria-hidden="true" /> RESET VIEW
          </button>
        </div>
      </header>
      <GraphCanvas graph={graph} resetEpoch={resetEpoch} onHover={onHover} />
      <footer className="arc-graph-inspector">
        {hovered ? (
          <>
            <strong>{hovered.label}</strong>
            <span>{hovered.kind.toUpperCase()}</span>
            {hovered.provenance ? <span>SOURCE / {hovered.provenance}</span> : null}
            {hovered.trusted === false ? <span className="danger">UNTRUSTED</span> : null}
          </>
        ) : (
          <span>DRAG TO PAN · SCROLL TO ZOOM · DRAG NODES TO MOVE THE GRAPH</span>
        )}
      </footer>
    </div>
  )
}
