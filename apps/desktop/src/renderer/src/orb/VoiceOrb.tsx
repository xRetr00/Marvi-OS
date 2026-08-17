// The Voice-page orb: a dense glowing particle sphere in the orange→red→pink→
// magenta family, on a faint perspective ground grid, camera slightly above
// front. It "breathes" with the live voice level — energy, not decoration.
// Distinct from the island orb (which uses the vendored thinking-orbs states).

import { useEffect, useRef } from 'react'

const N = 2000
const GOLDEN = Math.PI * (3 - Math.sqrt(5))

// Fibonacci lattice on the unit sphere.
const SPHERE: Array<[number, number, number]> = []
for (let i = 0; i < N; i += 1) {
  const y = 1 - (2 * (i + 0.5)) / N
  const r = Math.sqrt(Math.max(0, 1 - y * y))
  const theta = GOLDEN * i
  SPHERE.push([r * Math.cos(theta), y, r * Math.sin(theta)])
}

type RGB = [number, number, number]

// orange → red → pink → magenta (0 = cool/far, 1 = hot/near)
const STOPS: Array<[number, RGB]> = [
  [0.0, [0xa8, 0x55, 0xf7]],
  [0.33, [0xec, 0x48, 0x99]],
  [0.66, [0xef, 0x44, 0x44]],
  [1.0, [0xf9, 0x73, 0x16]]
]

function gradient(t: number): RGB {
  const x = Math.max(0, Math.min(1, t))
  for (let i = 0; i < STOPS.length - 1; i += 1) {
    const [t0, c0] = STOPS[i]
    const [t1, c1] = STOPS[i + 1]
    if (x >= t0 && x <= t1) {
      const f = (x - t0) / (t1 - t0)
      return [
        Math.round(c0[0] + (c1[0] - c0[0]) * f),
        Math.round(c0[1] + (c1[1] - c0[1]) * f),
        Math.round(c0[2] + (c1[2] - c0[2]) * f)
      ]
    }
  }
  return STOPS[STOPS.length - 1][1]
}

function drawGrid(ctx: CanvasRenderingContext2D, size: number): void {
  const w = size
  const h = size
  const horizon = h * 0.68
  const vpX = w * 0.5
  ctx.lineWidth = 1
  for (let i = 0; i <= 14; i += 1) {
    const x = (i / 14) * w
    ctx.strokeStyle = 'rgba(249,115,22,0.10)'
    ctx.beginPath()
    ctx.moveTo(vpX, horizon)
    ctx.lineTo(x, h)
    ctx.stroke()
  }
  for (let j = 1; j <= 7; j += 1) {
    const t = j / 7
    const y = horizon + (h - horizon) * (t * t)
    ctx.strokeStyle = 'rgba(249,115,22,0.12)'
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(w, y)
    ctx.stroke()
  }
  ctx.strokeStyle = 'rgba(249,115,22,0.16)'
  ctx.beginPath()
  ctx.moveTo(0, horizon)
  ctx.lineTo(w, horizon)
  ctx.stroke()
}

function draw(
  ctx: CanvasRenderingContext2D,
  size: number,
  t: number,
  level: number,
  active: boolean
): void {
  ctx.clearRect(0, 0, size, size)
  drawGrid(ctx, size)

  const cx = size / 2
  const cy = size / 2
  const tilt = 0.42
  const yaw = t * 0.22
  const sy = Math.sin(yaw)
  const cyw = Math.cos(yaw)
  const st = Math.sin(tilt)
  const ct = Math.cos(tilt)
  const breathe = active ? 0.7 + level * 1.0 : 0.7
  const scale = size * 0.34 * (1 + level * 0.12)

  for (const [x, y, z] of SPHERE) {
    const x1 = x * cyw + z * sy
    const z1 = -x * sy + z * cyw
    const y1 = y * ct - z1 * st
    const z2 = y * st + z1 * ct
    const depth = (z2 + 1) / 2
    const px = cx + x1 * scale
    const py = cy - y1 * scale
    const [r, g, b] = gradient(depth)
    const alpha = 0.3 + depth * 0.7
    const rad = Math.max(0.4, (0.5 + depth * 1.15) * breathe)
    ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`
    ctx.beginPath()
    ctx.arc(px, py, rad, 0, Math.PI * 2)
    ctx.fill()
  }
}

export function VoiceOrb({
  size,
  level = 0,
  active = false
}: {
  size: number
  level?: number
  active?: boolean
}): React.JSX.Element {
  const ref = useRef<HTMLCanvasElement | null>(null)
  const levelRef = useRef(level)
  const activeRef = useRef(active)
  useEffect(() => {
    levelRef.current = level
  }, [level])
  useEffect(() => {
    activeRef.current = active
  }, [active])

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const dpr = Math.min(2, window.devicePixelRatio || 1)
    canvas.width = Math.round(size * dpr)
    canvas.height = Math.round(size * dpr)
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let smoothed = levelRef.current
    const paint = (t: number): void => {
      // ease toward the live level so the orb breathes rather than jumps
      smoothed += (levelRef.current - smoothed) * 0.12
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      draw(ctx, size, t, smoothed, activeRef.current)
    }

    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      paint(0.6)
      return
    }

    let raf = 0
    const loop = (): void => {
      paint(performance.now() / 1000)
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [size])

  return (
    <canvas
      ref={ref}
      className="voice-orb"
      style={{ width: size, height: size, display: 'block' }}
      aria-hidden="true"
    />
  )
}
