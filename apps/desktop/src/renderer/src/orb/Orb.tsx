// The island orb: a vendored thinking-orbs animation tinted per phase and
// driven by live voice level. Small (inline 20px preset) and cheap — one
// canvas, one rAF loop, no filters.

import { useEffect, useRef } from 'react'

import { MODE_FRAMES, resolvePreset } from './engine'
import { paintFrame } from './paint'
import type { OrbSize, OrbState } from './types'

export function Orb({
  state,
  size,
  level = 0,
  accent = '#147ec1',
  reactive = false,
  className = 'orb'
}: {
  state: OrbState
  size: number
  level?: number
  accent?: string
  reactive?: boolean
  className?: string
}): React.JSX.Element {
  const ref = useRef<HTMLCanvasElement | null>(null)

  // Mutable inputs read by the loop without re-running the effect (level
  // changes every ~100ms — re-creating the loop would stutter the clock).
  const levelRef = useRef(level)
  const accentRef = useRef(accent)
  const reactiveRef = useRef(reactive)
  useEffect(() => {
    levelRef.current = level
  }, [level])
  useEffect(() => {
    accentRef.current = accent
  }, [accent])
  useEffect(() => {
    reactiveRef.current = reactive
  }, [reactive])

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const dpr = Math.min(2, window.devicePixelRatio || 1)
    canvas.width = Math.round(size * dpr)
    canvas.height = Math.round(size * dpr)
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const presetSize: OrbSize = size <= 40 ? 20 : 64
    const { mode, speed, opts } = resolvePreset(state, presetSize)
    const frame = MODE_FRAMES[mode]

    const draw = (t: number): void => {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, size, size)
      paintFrame(ctx, frame(size, t, opts), {
        accent: accentRef.current,
        level: levelRef.current,
        reactive: reactiveRef.current
      })
    }

    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      draw(0.6 * speed)
      return
    }

    let raf = 0
    const loop = (): void => {
      draw((performance.now() / 1000) * speed)
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [state, size])

  return (
    <canvas
      ref={ref}
      className={className}
      style={{ width: size, height: size, display: 'block' }}
      aria-hidden="true"
    />
  )
}
