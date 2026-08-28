import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
import { RotateCcw, Settings2 } from 'lucide-react'

import type { MemoryGraphNode, MemoryGraphPage } from '../../../shared/runtime'
import {
  DEFAULT_GRAPH_SETTINGS,
  memoryNodeColor,
  memoryNodeRadius,
  neighbourhood,
  seedMemoryGraph,
  type ForceGraphNode,
  type GraphSettings
} from './arc-memory-layout'

interface ArcMemoryGraphProps {
  graph: MemoryGraphPage
  loading?: boolean
  /** Opened when a node is clicked. The page owns what "details" means,
   * because a memory and an entity are edited in different ways. */
  onSelect?: (node: MemoryGraphNode | null) => void
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
  settings,
  resetEpoch,
  onHover,
  onSelect,
  selectedId
}: {
  graph: MemoryGraphPage
  settings: GraphSettings
  resetEpoch: number
  onHover: (node: MemoryGraphNode | null) => void
  onSelect: (node: MemoryGraphNode | null) => void
  selectedId: string
}): React.JSX.Element {
  const hostRef = useRef<HTMLDivElement | null>(null)
  // Read inside the render loop rather than closed over, so changing a force
  // slider does not tear the whole scene down and re-seed the layout. Written
  // in an effect rather than during render: a ref mutated while rendering is
  // a value React may have already thrown away.
  const live = useRef({ settings, selectedId, onHover, onSelect })
  useEffect(() => {
    live.current = { settings, selectedId, onHover, onSelect }
  })

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

      const seeded = seedMemoryGraph(graph)
      const nodes = live.current.settings.showOrphans
        ? seeded
        : seeded.filter((node) => node.degree > 0)
      const byId = new Map(nodes.map((node) => [node.id, node]))
      const links: ForceLink[] = graph.edges
        .filter((edge) => byId.has(edge.source) && byId.has(edge.target))
        .map((edge) => ({ id: edge.id, source: edge.source, target: edge.target }))
      const glyphs = new Map<string, Graphics>()
      const labels = new Map<string, Text>()

      /** What is lit. Empty means everything, which is the resting state. */
      let lit: Set<string> | null = null

      const paint = (node: ForceGraphNode): void => {
        const glyph = glyphs.get(node.id)
        if (!glyph) return
        const near = lit === null || lit.has(node.id)
        const radius = memoryNodeRadius(node, live.current.settings)
        const chosen = node.id === live.current.selectedId
        glyph
          .clear()
          .circle(0, 0, radius + 2.4)
          .fill({ color: memoryNodeColor(node), alpha: near ? 0.14 : 0.04 })
          .circle(0, 0, radius)
          .fill({ color: memoryNodeColor(node), alpha: near ? 0.96 : 0.16 })
        if (chosen) {
          // A ring rather than a colour change: the colour already means the
          // kind, and overloading it would cost more than the selection gains.
          glyph.circle(0, 0, radius + 4.5).stroke({ color: 0x4ba6df, width: 1.6, alpha: 0.95 })
        }
      }

      for (const node of nodes) {
        const glyph = new Graphics()
        glyph.eventMode = 'static'
        glyph.cursor = 'pointer'
        glyphs.set(node.id, glyph)
        nodesLayer.addChild(glyph)
        paint(node)

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
        labels.set(node.id, label)
        labelsLayer.addChild(label)

        glyph.on('pointerover', () => {
          // Obsidian's one interaction that makes a hairball legible: light
          // what this touches, dim the rest. 152 nodes around one hub says
          // nothing until you can ask what *this* one connects to.
          lit = neighbourhood(graph, node.id)
          for (const other of nodes) paint(other)
          live.current.onHover(node)
        })
        glyph.on('pointerout', () => {
          lit = null
          for (const other of nodes) paint(other)
          live.current.onHover(null)
        })
      }

      const draw = (): void => {
        const { settings: now } = live.current
        edges.clear()
        for (const link of links) {
          const source =
            typeof link.source === 'object' ? link.source : byId.get(String(link.source))
          const target =
            typeof link.target === 'object' ? link.target : byId.get(String(link.target))
          if (!source || !target) continue
          const near = lit === null || (lit.has(source.id) && lit.has(target.id))
          edges
            .moveTo(source.x, source.y)
            .lineTo(target.x, target.y)
            .stroke({
              color: near ? 0x8b93a0 : 0x50565f,
              alpha: near ? 0.55 : 0.1,
              width: now.linkThickness
            })
          if (now.showArrows && near) {
            // A short tick near the target, not a filled head: at this scale a
            // triangle is a blob, and direction is all it has to convey.
            const angle = Math.atan2(target.y - source.y, target.x - source.x)
            const back = memoryNodeRadius(target, now) + 3
            const tipX = target.x - Math.cos(angle) * back
            const tipY = target.y - Math.sin(angle) * back
            for (const spread of [2.6, -2.6]) {
              edges
                .moveTo(tipX, tipY)
                .lineTo(tipX + Math.cos(angle + spread) * 4, tipY + Math.sin(angle + spread) * 4)
                .stroke({ color: 0x8b93a0, alpha: 0.5, width: now.linkThickness })
            }
          }
        }
        // Labels fade with zoom rather than switching on and off. Every label
        // at once is noise; none at all is a starfield. The threshold is a
        // setting because the right answer depends on how big the graph is.
        const zoom = world.scale.x
        const visible = zoom >= now.textFade
        const fade = Math.min(1, Math.max(0, (zoom - now.textFade) / 0.45))
        for (const node of nodes) {
          glyphs.get(node.id)?.position.set(node.x, node.y)
          const label = labels.get(node.id)
          if (!label) continue
          const near = lit === null || lit.has(node.id)
          // A hovered neighbourhood always shows its names, whatever the zoom.
          label.visible = (visible || lit !== null) && near
          label.alpha = lit !== null ? 1 : fade
          label.position.set(node.x, node.y + memoryNodeRadius(node, now) + 7)
        }
      }

      const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      const simulation = forceSimulation(nodes)
        .force(
          'links',
          forceLink<ForceGraphNode, ForceLink>(links)
            .id((node) => node.id)
            .distance(settings.linkDistance)
            .strength(settings.linkForce)
        )
        .force(
          'charge',
          forceManyBody().strength(-settings.repelForce).distanceMax(520).theta(0.9)
        )
        .force('center', forceCenter(0, 0).strength(settings.centerForce))
        .force(
          'collide',
          forceCollide<ForceGraphNode>().radius(
            (node) => memoryNodeRadius(node, live.current.settings) + 9
          )
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
        draw()
      }
      fit()
      const fitTimer = window.setTimeout(fit, reducedMotion ? 0 : 900)

      let panning = false
      let dragNode: ForceGraphNode | null = null
      let movedWhileDown = false
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
          movedWhileDown = true
          const point = toWorld(event)
          dragNode.fx = point.x
          dragNode.fy = point.y
          simulation.alphaTarget(0.22).restart()
          return
        }
        if (!panning) return
        movedWhileDown = true
        world.position.x += event.clientX - lastX
        world.position.y += event.clientY - lastY
        lastX = event.clientX
        lastY = event.clientY
        draw()
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
        movedWhileDown = false
        lastX = event.clientX
        lastY = event.clientY
      }
      // A click on the background clears the selection, the way closing a note
      // does. Only when it was a click: a drag that ends over nothing is a pan.
      const canvasClick = (): void => {
        if (!movedWhileDown) live.current.onSelect(null)
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
        // Redrawn immediately so labels fade as you scroll rather than at the
        // next physics tick, which on a settled graph never comes.
        draw()
      }
      for (const node of nodes) {
        const glyph = glyphs.get(node.id)
        glyph?.on('pointerdown', (event: FederatedPointerEvent) => {
          event.stopPropagation()
          dragNode = node
          movedWhileDown = false
          node.fx = node.x
          node.fy = node.y
        })
        glyph?.on('pointerup', (event: FederatedPointerEvent) => {
          event.stopPropagation()
          // A drag moved it; a click chose it. Same button, told apart by
          // whether the pointer travelled.
          if (!movedWhileDown) live.current.onSelect(node)
        })
      }
      app.canvas.addEventListener('pointerdown', pointerDown)
      app.canvas.addEventListener('click', canvasClick)
      app.canvas.addEventListener('wheel', wheel, { passive: false })
      window.addEventListener('pointermove', pointerMove)
      window.addEventListener('pointerup', pointerUp)

      cleanup = () => {
        window.clearTimeout(fitTimer)
        simulation.stop()
        app.canvas.removeEventListener('pointerdown', pointerDown)
        app.canvas.removeEventListener('click', canvasClick)
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
    // The forces and the orphan filter rebuild the scene; everything else is
    // read live from the ref above, so dragging a slider does not re-seed.
  }, [
    graph,
    resetEpoch,
    settings.centerForce,
    settings.repelForce,
    settings.linkForce,
    settings.linkDistance,
    settings.showOrphans
  ])

  return <div className="arc-graph-canvas" ref={hostRef} />
}

/** One force slider. Named and ranged the way Obsidian names and ranges them. */
function Force({
  label,
  value,
  min,
  max,
  step,
  onChange
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
}): React.JSX.Element {
  return (
    <label className="arc-graph-force">
      <span>{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  )
}

export function ArcMemoryGraph({
  graph,
  loading = false,
  onSelect
}: ArcMemoryGraphProps): React.JSX.Element {
  const [hovered, setHovered] = useState<MemoryGraphNode | null>(null)
  const [selected, setSelected] = useState<MemoryGraphNode | null>(null)
  const [resetEpoch, setResetEpoch] = useState(0)
  const [settings, setSettings] = useState<GraphSettings>(DEFAULT_GRAPH_SETTINGS)
  const [showSettings, setShowSettings] = useState(false)
  const [query, setQuery] = useState('')

  const onHover = useCallback((node: MemoryGraphNode | null) => setHovered(node), [])
  const choose = useCallback(
    (node: MemoryGraphNode | null) => {
      setSelected(node)
      onSelect?.(node)
    },
    [onSelect]
  )

  // Filtering happens here rather than in the canvas so the counts in the
  // header describe what is actually on screen.
  const shown = useMemo<MemoryGraphPage>(() => {
    const term = query.trim().toLowerCase()
    if (!term) return graph
    const keep = new Set(
      graph.nodes.filter((node) => node.label.toLowerCase().includes(term)).map((node) => node.id)
    )
    // One hop out from every match, so a search shows a thing in its context
    // rather than a row of disconnected dots.
    for (const edge of graph.edges) {
      if (keep.has(edge.source)) keep.add(edge.target)
      else if (keep.has(edge.target)) keep.add(edge.source)
    }
    return {
      mode: graph.mode,
      nodes: graph.nodes.filter((node) => keep.has(node.id)),
      edges: graph.edges.filter((edge) => keep.has(edge.source) && keep.has(edge.target))
    }
  }, [graph, query])

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
          <span>{shown.nodes.length} NODES</span>
          <i>·</i>
          <span>{shown.edges.length} LINKS</span>
        </div>
        <input
          className="arc-graph-search"
          type="search"
          placeholder="Search the graph"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <div className="arc-graph-legend" aria-label="Graph legend">
          {legend.map(([label, kind]) => (
            <span key={label}>
              <i className={`arc-graph-key arc-graph-node-${kind}`} /> {label}
            </span>
          ))}
          <button
            type="button"
            aria-pressed={showSettings}
            onClick={() => setShowSettings((open) => !open)}
          >
            <Settings2 aria-hidden="true" /> FORCES
          </button>
          <button type="button" onClick={() => setResetEpoch((value) => value + 1)}>
            <RotateCcw aria-hidden="true" /> RESET VIEW
          </button>
        </div>
      </header>

      {showSettings ? (
        <div className="arc-graph-settings">
          <Force
            label="Center force"
            value={settings.centerForce}
            min={0}
            max={0.3}
            step={0.005}
            onChange={(centerForce) => setSettings((now) => ({ ...now, centerForce }))}
          />
          <Force
            label="Repel force"
            value={settings.repelForce}
            min={10}
            max={400}
            step={5}
            onChange={(repelForce) => setSettings((now) => ({ ...now, repelForce }))}
          />
          <Force
            label="Link force"
            value={settings.linkForce}
            min={0}
            max={1}
            step={0.02}
            onChange={(linkForce) => setSettings((now) => ({ ...now, linkForce }))}
          />
          <Force
            label="Link distance"
            value={settings.linkDistance}
            min={20}
            max={220}
            step={2}
            onChange={(linkDistance) => setSettings((now) => ({ ...now, linkDistance }))}
          />
          <Force
            label="Node size"
            value={settings.nodeSize}
            min={0.4}
            max={2.4}
            step={0.05}
            onChange={(nodeSize) => setSettings((now) => ({ ...now, nodeSize }))}
          />
          <Force
            label="Link thickness"
            value={settings.linkThickness}
            min={0.3}
            max={3}
            step={0.05}
            onChange={(linkThickness) => setSettings((now) => ({ ...now, linkThickness }))}
          />
          <Force
            label="Text fade"
            value={settings.textFade}
            min={0.1}
            max={2.5}
            step={0.05}
            onChange={(textFade) => setSettings((now) => ({ ...now, textFade }))}
          />
          <label className="arc-graph-force arc-graph-toggle">
            <span>Arrows</span>
            <input
              type="checkbox"
              checked={settings.showArrows}
              onChange={(event) =>
                setSettings((now) => ({ ...now, showArrows: event.target.checked }))
              }
            />
          </label>
          <label className="arc-graph-force arc-graph-toggle">
            <span>Orphans</span>
            <input
              type="checkbox"
              checked={settings.showOrphans}
              onChange={(event) =>
                setSettings((now) => ({ ...now, showOrphans: event.target.checked }))
              }
            />
          </label>
          <button type="button" onClick={() => setSettings(DEFAULT_GRAPH_SETTINGS)}>
            Defaults
          </button>
        </div>
      ) : null}

      <GraphCanvas
        graph={shown}
        settings={settings}
        resetEpoch={resetEpoch}
        onHover={onHover}
        onSelect={choose}
        selectedId={selected?.id ?? ''}
      />
      <footer className="arc-graph-inspector">
        {hovered ?? selected ? (
          <>
            <strong>{(hovered ?? selected)?.label}</strong>
            <span>{(hovered ?? selected)?.kind.toUpperCase()}</span>
            {(hovered ?? selected)?.provenance ? (
              <span>SOURCE / {(hovered ?? selected)?.provenance}</span>
            ) : null}
            {(hovered ?? selected)?.trusted === false ? (
              <span className="danger">UNTRUSTED</span>
            ) : null}
          </>
        ) : (
          <span>CLICK A NODE TO OPEN IT · DRAG TO PAN · SCROLL TO ZOOM</span>
        )}
      </footer>
    </div>
  )
}
