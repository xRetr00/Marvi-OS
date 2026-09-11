/**
 * A sub-agent's face: a seeded 6x6 pixel grid in a circle.
 *
 * The owner's design, adapted for this renderer: no `"use client"` (there is
 * no server here), and the class list is joined by hand because the renderer
 * has no `cn` and no Tailwind (see `ui/avatar.tsx`).
 *
 * The one place colour is allowed in Marvi's UI (`docs/UI.md`). Everything
 * around an avatar stays monochrome.
 *
 * `animated` is the caller's to decide, and the callers pass it only for an
 * agent that is working: a roster of canvases all breathing at 60 fps would
 * spend frames on nothing, and a still face reads as "idle" at a glance.
 * Reduced motion always wins.
 */

import { useEffect, useRef } from 'react'

import { generateGrid, generatePalette, hashSeed, GRID_SIZE } from './avatar-pattern'

export type AgentAvatarProps = Omit<React.CanvasHTMLAttributes<HTMLCanvasElement>, 'children'> & {
  /** String seed to generate a unique deterministic avatar pattern */
  seed: string
  /** Diameter in pixels */
  size?: number
  /** Enable pixel animation (respects prefers-reduced-motion) */
  animated?: boolean
  /** Accessible name; defaults to the seed. */
  label?: string
}

/** Pulse: each pixel oscillates lightness independently */
const PULSE_SPEED = 0.002
const PULSE_AMPLITUDE = 22

/** Breathe: global slow scale oscillation */
const BREATHE_SPEED = 0.001
const BREATHE_AMPLITUDE = 10

/** Wave: diagonal sweep across the grid */
const WAVE_SPEED = 0.0015
const WAVE_AMPLITUDE = 15
const WAVE_LENGTH = 3

/** Sparkle: random bright flashes */
const SPARKLE_SPEED = 0.004
const SPARKLE_THRESHOLD = 0.92
const SPARKLE_BOOST = 25

/** Scale pulse: whole avatar breathes in size */
const SCALE_PULSE_SPEED = 0.0008
const SCALE_PULSE_AMOUNT = 0.03

const GLOW_RADIUS_RATIO = 0.25

export function AgentAvatar({
  seed,
  size = 64,
  animated = true,
  label,
  className,
  ...props
}: AgentAvatarProps): React.JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = size * dpr
    canvas.height = size * dpr
    ctx.scale(dpr, dpr)

    const hash = hashSeed(seed)
    const palette = generatePalette(hash)
    const grid = generateGrid(hash)
    const cellSize = size / GRID_SIZE
    const half = size / 2

    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    let shouldAnimate = animated && !motionQuery.matches

    const draw = (time: number): void => {
      ctx.clearRect(0, 0, size, size)

      // Scale pulse — whole avatar breathes
      const scale = shouldAnimate ? 1 + Math.sin(time * SCALE_PULSE_SPEED) * SCALE_PULSE_AMOUNT : 1

      ctx.save()
      ctx.translate(half, half)
      ctx.scale(scale, scale)
      ctx.translate(-half, -half)

      // Clip to circle
      ctx.beginPath()
      ctx.arc(half, half, half, 0, Math.PI * 2)
      ctx.clip()

      // Dark background
      ctx.fillStyle = '#08080f'
      ctx.fillRect(0, 0, size, size)

      // Global breathe offset for lightness
      const breatheOffset = shouldAnimate ? Math.sin(time * BREATHE_SPEED) * BREATHE_AMPLITUDE : 0

      for (let y = 0; y < GRID_SIZE; y++) {
        for (let x = 0; x < GRID_SIZE; x++) {
          const cell = grid[y][x]
          const [h, s, l] = palette[cell.colorIndex]

          const pulse = shouldAnimate ? Math.sin(time * PULSE_SPEED + cell.phase) * PULSE_AMPLITUDE : 0
          const waveDist = (x + y) / WAVE_LENGTH
          const wave = shouldAnimate ? Math.sin(time * WAVE_SPEED + waveDist) * WAVE_AMPLITUDE : 0
          const sparkleVal = shouldAnimate ? Math.sin(time * SPARKLE_SPEED + cell.sparklePhase) : 0
          const sparkle =
            sparkleVal > SPARKLE_THRESHOLD
              ? ((sparkleVal - SPARKLE_THRESHOLD) / (1 - SPARKLE_THRESHOLD)) * SPARKLE_BOOST
              : 0

          const finalLight = Math.min(
            90,
            Math.max(20, (l + pulse + breatheOffset + wave + sparkle) * cell.brightness)
          )
          const finalSat = Math.min(100, s + 5)

          // Pixel glow — subtle shadow per cell
          ctx.shadowColor = `hsl(${h}, ${finalSat}%, ${finalLight}%)`
          ctx.shadowBlur = cellSize * 0.45
          ctx.fillStyle = `hsl(${h}, ${finalSat}%, ${finalLight}%)`
          ctx.fillRect(x * cellSize, y * cellSize, cellSize, cellSize)
        }
      }

      ctx.shadowBlur = 0
      ctx.restore()

      // Outer glow ring
      const [gh, gs, gl] = palette[0]
      ctx.save()
      ctx.globalCompositeOperation = 'screen'
      ctx.shadowColor = `hsla(${gh}, ${gs}%, ${gl}%, 0.6)`
      ctx.shadowBlur = size * GLOW_RADIUS_RATIO
      ctx.beginPath()
      ctx.arc(half, half, half - 1, 0, Math.PI * 2)
      ctx.strokeStyle = `hsla(${gh}, ${gs}%, ${gl}%, 0.15)`
      ctx.lineWidth = 2
      ctx.stroke()
      ctx.restore()

      if (shouldAnimate) rafRef.current = requestAnimationFrame(draw)
    }

    const handleMotionChange = (): void => {
      cancelAnimationFrame(rafRef.current)
      shouldAnimate = animated && !motionQuery.matches
      if (shouldAnimate) rafRef.current = requestAnimationFrame(draw)
      else draw(0)
    }

    motionQuery.addEventListener('change', handleMotionChange)
    if (shouldAnimate) rafRef.current = requestAnimationFrame(draw)
    else draw(0)

    return () => {
      cancelAnimationFrame(rafRef.current)
      motionQuery.removeEventListener('change', handleMotionChange)
    }
  }, [seed, size, animated])

  return (
    <canvas
      aria-label={label ?? `Avatar for ${seed}`}
      className={className ? `agent-avatar ${className}` : 'agent-avatar'}
      ref={canvasRef}
      role="img"
      style={{ height: size, width: size }}
      {...props}
    />
  )
}
