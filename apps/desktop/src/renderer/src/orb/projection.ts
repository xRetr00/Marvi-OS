/** Perspective and directional lighting for Marvi's existing unit-sphere mesh. */
export function projectVoicePoint(
  x: number,
  y: number,
  z: number
): {
  x: number
  y: number
  perspective: number
  light: number
  visible: boolean
} {
  const camera = 3.5
  const length = Math.hypot(x, y, z) || 1
  const perspective = camera / Math.max(0.5, camera - z)
  const diffuse = Math.max(0, (-0.45 * x + 0.55 * y + 0.7 * z) / length)
  return {
    x: x * perspective,
    y: y * perspective,
    perspective,
    light: 0.22 + 0.78 * diffuse,
    // Surface normal faces the perspective camera, not just the screen plane.
    visible: z * camera > length * length
  }
}
