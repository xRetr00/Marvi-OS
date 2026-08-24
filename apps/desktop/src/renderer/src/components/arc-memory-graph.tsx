import { useMemo, useRef, useState } from 'react'
import { RotateCcw } from 'lucide-react'

import type { MemoryGraphNode, MemoryGraphPage } from '../../../shared/runtime'
import { layoutMemoryGraph, type GraphPoint } from './arc-memory-layout'

const WIDTH = 1000
const HEIGHT = 620

function nodeRadius(node: MemoryGraphNode): number {
  if (node.kind === 'root') return 17
  if (node.kind === 'source') return 11
  if (node.kind === 'summary' || node.kind === 'contact') return 8
  return 5
}

function nodeClass(node: MemoryGraphNode): string {
  if (node.trusted === false) return 'arc-graph-node-untrusted'
  return `arc-graph-node-${node.kind}`
}

interface ArcMemoryGraphProps {
  graph: MemoryGraphPage
  loading?: boolean
}

export function ArcMemoryGraph({ graph, loading = false }: ArcMemoryGraphProps): React.JSX.Element {
  const seeded = useMemo(() => layoutMemoryGraph(graph), [graph])
  const [positionOverrides, setPositionOverrides] = useState(
    () => new Map<string, { x: number; y: number }>()
  )
  const points = useMemo(
    () =>
      seeded.map((point) => ({
        ...point,
        ...(positionOverrides.get(point.id) ?? {})
      })),
    [positionOverrides, seeded]
  )
  const [hovered, setHovered] = useState<GraphPoint | null>(null)
  const [view, setView] = useState({ x: 0, y: 0, width: WIDTH, height: HEIGHT })
  const svgRef = useRef<SVGSVGElement | null>(null)
  const dragRef = useRef<
    | { kind: 'node'; id: string; x: number; y: number }
    | { kind: 'canvas'; x: number; y: number; viewX: number; viewY: number }
    | null
  >(null)

  const pointById = useMemo(() => new Map(points.map((point) => [point.id, point])), [points])
  const reset = (): void => {
    setPositionOverrides(new Map())
    setView({ x: 0, y: 0, width: WIDTH, height: HEIGHT })
  }
  const clientPoint = (clientX: number, clientY: number): { x: number; y: number } | null => {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect || rect.width === 0 || rect.height === 0) return null
    return {
      x: view.x + ((clientX - rect.left) / rect.width) * view.width,
      y: view.y + ((clientY - rect.top) / rect.height) * view.height
    }
  }

  if (loading) {
    return <div className="arc-graph-empty">BUILDING ARC GRAPH…</div>
  }
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
          <button type="button" onClick={reset}>
            <RotateCcw aria-hidden="true" /> RESET VIEW
          </button>
        </div>
      </header>
      <svg
        ref={svgRef}
        aria-label="Interactive ARC memory graph"
        className="arc-graph-canvas"
        data-testid="arc-memory-graph"
        viewBox={`${view.x} ${view.y} ${view.width} ${view.height}`}
        onPointerDown={(event) => {
          const at = clientPoint(event.clientX, event.clientY)
          if (!at) return
          dragRef.current = {
            kind: 'canvas',
            x: at.x,
            y: at.y,
            viewX: view.x,
            viewY: view.y
          }
          event.currentTarget.setPointerCapture(event.pointerId)
        }}
        onPointerMove={(event) => {
          const drag = dragRef.current
          const at = clientPoint(event.clientX, event.clientY)
          if (!drag || !at) return
          if (drag.kind === 'node') {
            setPositionOverrides((current) => {
              const next = new Map(current)
              next.set(drag.id, { x: at.x, y: at.y })
              return next
            })
            dragRef.current = { ...drag, x: at.x, y: at.y }
          } else {
            setView((current) => ({
              ...current,
              x: drag.viewX - (at.x - drag.x),
              y: drag.viewY - (at.y - drag.y)
            }))
          }
        }}
        onPointerUp={() => {
          dragRef.current = null
        }}
        onPointerCancel={() => {
          dragRef.current = null
        }}
        onWheel={(event) => {
          event.preventDefault()
          const factor = event.deltaY > 0 ? 1.12 : 0.89
          const nextWidth = Math.min(2000, Math.max(360, view.width * factor))
          const nextHeight = (nextWidth / WIDTH) * HEIGHT
          setView((current) => ({
            x: current.x + (current.width - nextWidth) / 2,
            y: current.y + (current.height - nextHeight) / 2,
            width: nextWidth,
            height: nextHeight
          }))
        }}
      >
        <g className="arc-graph-edges">
          {graph.edges.map((edge) => {
            const source = pointById.get(edge.source)
            const target = pointById.get(edge.target)
            if (!source || !target) return null
            return (
              <line key={edge.id} x1={source.x} y1={source.y} x2={target.x} y2={target.y}>
                <title>{edge.label || 'memory link'}</title>
              </line>
            )
          })}
        </g>
        <g>
          {points.map((point) => (
            <g
              className="arc-graph-node"
              key={point.id}
              onPointerDown={(event) => {
                event.stopPropagation()
                const at = clientPoint(event.clientX, event.clientY)
                if (!at) return
                dragRef.current = { kind: 'node', id: point.id, x: at.x, y: at.y }
                event.currentTarget.setPointerCapture(event.pointerId)
              }}
              onMouseEnter={() => setHovered(point)}
            >
              <circle
                className={nodeClass(point)}
                cx={point.x}
                cy={point.y}
                r={nodeRadius(point)}
              />
              {(point.kind === 'root' || point.kind === 'source' || point.kind === 'contact') && (
                <text x={point.x} y={point.y + nodeRadius(point) + 18} textAnchor="middle">
                  {point.label.length > 22 ? `${point.label.slice(0, 21)}…` : point.label}
                </text>
              )}
            </g>
          ))}
        </g>
      </svg>
      <footer className="arc-graph-inspector">
        {hovered ? (
          <>
            <strong>{hovered.label}</strong>
            <span>{hovered.kind.toUpperCase()}</span>
            {hovered.provenance ? <span>SOURCE / {hovered.provenance}</span> : null}
            {hovered.trusted === false ? <span className="danger">UNTRUSTED</span> : null}
          </>
        ) : (
          <span>DRAG TO PAN · SCROLL TO ZOOM · DRAG NODES TO ARRANGE</span>
        )}
      </footer>
    </div>
  )
}
