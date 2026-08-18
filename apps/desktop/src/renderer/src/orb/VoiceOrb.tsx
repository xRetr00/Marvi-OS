// The Voice-page orb: a dense glowing particle sphere in the orange→red→pink→
// magenta family, on a faint perspective ground grid, camera slightly above
// front. It "breathes" with the live voice level — energy, not decoration.
// Distinct from the island orb (which uses the vendored thinking-orbs states).

import { useEffect, useRef } from 'react'

import { MOOD_FOR_PHASE, RAMPS, blend, type Ramp } from './moods'

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

interface Frame {
  width: number
  height: number
  t: number
  level: number
  active: boolean
  /** Mood ramps, and how far between them. */
  from: Ramp
  to: Ramp
  mix: number
  /** Pointer-driven rotation, in radians. */
  yaw: number
  pitch: number
}

function draw(ctx: CanvasRenderingContext2D, f: Frame): void {
  ctx.clearRect(0, 0, f.width, f.height)
  drawGrid(ctx, f.width, f.height)

  const cx = f.width / 2
  const cy = f.height / 2
  // The sphere is sized off the smaller axis so a wide window makes a bigger
  // orb rather than an ellipse cropped by the sides.
  const reach = Math.min(f.width, f.height)

  const tilt = 0.42 + f.pitch
  const yaw = f.t * 0.22 + f.yaw
  const sy = Math.sin(yaw)
  const cyw = Math.cos(yaw)
  const st = Math.sin(tilt)
  const ct = Math.cos(tilt)
  const breathe = f.active ? 0.7 + f.level * 1.0 : 0.7
  const scale = reach * 0.34 * (1 + f.level * 0.12)

  for (const [x, y, z] of SPHERE) {
    const x1 = x * cyw + z * sy
    const z1 = -x * sy + z * cyw
    const y1 = y * ct - z1 * st
    const z2 = y * st + z1 * ct
    const depth = (z2 + 1) / 2
    const px = cx + x1 * scale
    const py = cy - y1 * scale
    const [r, g, b] = blend(f.from, f.to, f.mix, depth)
    const alpha = 0.3 + depth * 0.7
    const rad = Math.max(0.4, (0.5 + depth * 1.15) * breathe)
    ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`
    ctx.beginPath()
    ctx.arc(px, py, rad, 0, Math.PI * 2)
    ctx.fill()
  }
}

export function VoiceOrb({
  phase = 'ready',
  level = 0,
  active = false,
  interactive = true
}: {
  /** Drives the colour. Unknown phases rest on the idle ramp. */
  phase?: string
  level?: number
  active?: boolean
  /** Pointer rotation. Off for the small island orb, which is not a surface
   * anyone points at. */
  interactive?: boolean
}): React.JSX.Element {
  const ref = useRef<HTMLCanvasElement | null>(null)
  const levelRef = useRef(level)
  const activeRef = useRef(active)
  const phaseRef = useRef(phase)
  // Pointer target and the eased value chasing it, so a flick of the mouse is
  // a glide rather than a snap.
  const aim = useRef({ yaw: 0, pitch: 0 })
  const eased = useRef({ yaw: 0, pitch: 0 })

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
    const started = performance.now()

    const loop = (now: number): void => {
      const t = (now - started) / 1000
      smoothed += (levelRef.current - smoothed) * 0.12

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

      eased.current.yaw += (aim.current.yaw - eased.current.yaw) * 0.08
      eased.current.pitch += (aim.current.pitch - eased.current.pitch) * 0.08

      draw(ctx, {
        width,
        height,
        t,
        level: smoothed,
        active: activeRef.current,
        from,
        to,
        mix,
        yaw: eased.current.yaw,
        pitch: eased.current.pitch
      })
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)

    return () => {
      cancelAnimationFrame(raf)
      observer.disconnect()
    }
  }, [])

  useEffect(() => {
    if (!interactive) return
    const surface = ref.current?.parentElement
    if (!surface) return

    const move = (event: PointerEvent): void => {
      const box = surface.getBoundingClientRect()
      // -1..1 from the centre. Yaw turns further than pitch because a sphere
      // tipped too far shows its pole and stops reading as a sphere.
      const nx = ((event.clientX - box.left) / box.width) * 2 - 1
      const ny = ((event.clientY - box.top) / box.height) * 2 - 1
      aim.current.yaw = nx * 0.9
      aim.current.pitch = -ny * 0.35
    }
    const leave = (): void => {
      aim.current.yaw = 0
      aim.current.pitch = 0
    }

    surface.addEventListener('pointermove', move)
    surface.addEventListener('pointerleave', leave)
    return () => {
      surface.removeEventListener('pointermove', move)
      surface.removeEventListener('pointerleave', leave)
    }
  }, [interactive])

  return <canvas className="voice-orb-canvas" ref={ref} />
}
