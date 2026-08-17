// Marvi's painter: colorizes the vendored thinking-orbs geometry.
//
// The engine emits monochrome "ink" (each dot carries `white` = depth 0..1).
// Marvi draws dots in the phase accent, keeping the depth shading so near dots
// read bright and far dots dim. A `level` (0..1, from the mic) scales dot
// radius/brightness for the listening/speaking phases.

import type { OrbFrame } from './engine'

export interface PaintOptions {
  /** Accent color (hex) to tint the dots. */
  accent: string
  /** Voice level 0..1 — scales dot energy for reactive phases. */
  level?: number
  /** When true, radius/brightness follow the level (listening/speaking). */
  reactive?: boolean
}

function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x))
}

function hexToRgb(hex: string): [number, number, number] {
  const value = hex.replace('#', '')
  const n =
    value.length === 3
      ? parseInt(
          value
            .split('')
            .map((c) => c + c)
            .join(''),
          16
        )
      : parseInt(value, 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

export function paintFrame(
  ctx: CanvasRenderingContext2D,
  frame: OrbFrame,
  options: PaintOptions
): void {
  const [r, g, b] = hexToRgb(options.accent)
  const level = clamp01(options.level ?? 0)

  const reactRadius = options.reactive ? 0.55 + level * 1.1 : 1
  const reactAlpha = options.reactive ? 0.5 + level * 0.6 : 1

  // edges first so nodes sit on top
  for (const line of frame.lines) {
    const alpha = (line.a ?? 1) * 0.45
    ctx.strokeStyle = `rgba(${r},${g},${b},${alpha})`
    ctx.lineWidth = line.w
    ctx.beginPath()
    ctx.moveTo(line.x1, line.y1)
    ctx.lineTo(line.x2, line.y2)
    ctx.stroke()
  }

  for (const dot of frame.dots) {
    // `white` is ink (0 = near/bright, 1 = far/dim); invert for brightness.
    const depth = 1 - clamp01(dot.white)
    const alpha = Math.min(1, (dot.a ?? 1) * reactAlpha * (0.3 + 0.7 * depth))
    ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`
    ctx.beginPath()
    ctx.arc(dot.x, dot.y, Math.max(0.3, dot.r * reactRadius), 0, Math.PI * 2)
    ctx.fill()
  }
}
