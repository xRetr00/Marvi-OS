// The Voice-page orb: one coherent dotted surface. Audio pushes a travelling
// wave through the whole sphere; there is no per-dot noise and no pointer
// steering. Silence therefore has a stable shape and speech has readable
// motion instead of particle jitter.

import { useEffect, useRef } from 'react'

import { MOOD_FOR_PHASE, RAMPS, blend, type Ramp } from './moods'
import { coherentWaveScale } from './wave'

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

function drawGrid(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const horizon = h * 0.72
  const vpX = w * 0.5
  ctx.lineWidth = 1
  for (let i = 0; i <= 10; i += 1) {
    const x = (i / 10) * w
    ctx.strokeStyle = 'rgba(48,50,54,0.34)'
    ctx.beginPath()
    ctx.moveTo(vpX, horizon)
    ctx.lineTo(x, h)
    ctx.stroke()
  }
  for (let j = 1; j <= 5; j += 1) {
    const t = j / 5
    const y = horizon + (h - horizon) * (t * t)
    ctx.strokeStyle = 'rgba(48,50,54,0.28)'
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(w, y)
    ctx.stroke()
  }
  ctx.strokeStyle = 'rgba(20,126,193,0.24)'
  ctx.beginPath()
  ctx.moveTo(0, horizon)
  ctx.lineTo(w, horizon)
  ctx.stroke()
}

interface Frame {
  width: number
  height: number
  wavePhase: number
  level: number
  active: boolean
  /** Mood ramps, and how far between them. */
  from: Ramp
  to: Ramp
  mix: number
}

function draw(ctx: CanvasRenderingContext2D, f: Frame): void {
  ctx.clearRect(0, 0, f.width, f.height)
  drawGrid(ctx, f.width, f.height)

  const cx = f.width / 2
  const cy = f.height / 2
  // The sphere is sized off the smaller axis so a wide window makes a bigger
  // orb rather than an ellipse cropped by the sides.
  const reach = Math.min(f.width, f.height)

  const tilt = 0.42
  // Rotation advances from the same audio envelope as the wave. There is no
  // idle spin: when the room is silent, the orb is silent too.
  const yaw = f.wavePhase * 0.055
  const sy = Math.sin(yaw)
  const cyw = Math.cos(yaw)
  const st = Math.sin(tilt)
  const ct = Math.cos(tilt)
  const energy = f.active ? Math.min(1, Math.max(0, f.level) * 1.35) : 0
  const dotScale = 0.72 + energy * 0.82
  const scale = reach * 0.33

  for (const point of SPHERE) {
    const [x, y, z] = point
    const wave = coherentWaveScale(point, f.wavePhase, energy)
    const wx = x * wave
    const wy = y * wave
    const wz = z * wave
    const x1 = wx * cyw + wz * sy
    const z1 = -wx * sy + wz * cyw
    const y1 = wy * ct - z1 * st
    const z2 = wy * st + z1 * ct
    const depth = (z2 + 1) / 2
    const px = cx + x1 * scale
    const py = cy - y1 * scale
    const [r, g, b] = blend(f.from, f.to, f.mix, depth)
    const alpha = 0.3 + depth * 0.7
    const rad = Math.max(0.42, (0.5 + depth * 1.05) * dotScale)
    ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`
    ctx.beginPath()
    ctx.arc(px, py, rad, 0, Math.PI * 2)
    ctx.fill()
  }
}

export function VoiceOrb({
  phase = 'ready',
  level = 0,
  active = false
}: {
  /** Drives the colour. Unknown phases rest on the idle ramp. */
  phase?: string
  level?: number
  active?: boolean
}): React.JSX.Element {
  const ref = useRef<HTMLCanvasElement | null>(null)
  const levelRef = useRef(level)
  const activeRef = useRef(active)
  const phaseRef = useRef(phase)

  useEffect(() => {
    levelRef.current = level
  }, [level])
  useEffect(() => {
    activeRef.current = active
  }, [active])
  useEffect(() => {
    phaseRef.current = phase
  }, [phase])

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // Fill whatever box the layout gives, and follow it when that changes.
    let width = 0
    let height = 0
    const resize = (): void => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const box = canvas.parentElement?.getBoundingClientRect()
      width = Math.max(1, Math.round(box?.width ?? canvas.clientWidth))
      height = Math.max(1, Math.round(box?.height ?? canvas.clientHeight))
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    const observer = new ResizeObserver(resize)
    if (canvas.parentElement) observer.observe(canvas.parentElement)

    // Mood crossfade: the ramp we are leaving, the one we are entering, and
    // how far across. Without this a phase change is a jump cut.
    let from = RAMPS.idle
    let to = RAMPS.idle
    let mix = 1
    let mood = 'idle'

    let raf = 0
    let smoothed = levelRef.current
    let last = performance.now()
    let wavePhase = 0
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    const loop = (now: number): void => {
      const delta = Math.min(0.05, Math.max(0, (now - last) / 1000))
      last = now
      smoothed += (levelRef.current - smoothed) * 0.12
      const audioEnergy = activeRef.current ? Math.max(0, Math.min(1, smoothed)) : 0
      if (!reducedMotion && audioEnergy > 0.01) {
        wavePhase += delta * (0.8 + audioEnergy * 4.2)
      }

      const wanted = MOOD_FOR_PHASE[phaseRef.current] ?? 'idle'
      if (wanted !== mood) {
        // Start the new sweep from wherever the last one had reached, so
        // changing phase twice quickly does not snap back.
        from = mix >= 1 ? to : from
        to = RAMPS[wanted] ?? RAMPS.idle
        mood = wanted
        mix = 0
      }
      if (mix < 1) mix = Math.min(1, mix + 0.03)

      draw(ctx, {
        width,
        height,
        wavePhase,
        level: smoothed,
        active: activeRef.current,
        from,
        to,
        mix
      })
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)

    return () => {
      cancelAnimationFrame(raf)
      observer.disconnect()
    }
  }, [])

  return <canvas aria-label="Voice activity orb" className="voice-orb-canvas" ref={ref} />
}
