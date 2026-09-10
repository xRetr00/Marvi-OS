/** Fold the original spherical particle lattice through an extra coordinate.
 * Bounded 4D rotations preserve the orb silhouette instead of replacing it. */
export function hyperWavePoint(
  point: readonly [number, number, number], time: number, energy: number
): [number, number, number] {
  const e = Number.isFinite(energy) ? Math.max(0, Math.min(1, energy)) : 0
  const [x, y, z] = point
  // Cartesian fields avoid a seam at longitude +/- pi and at the poles.
  const fold = Math.sin(3.2 * y + 1.8 * z - time * 0.8)
  const radius = 1 + (0.07 + e * 0.19) * fold
  const w = (0.22 + e * 0.32) * Math.sin(2.6 * x - 2.2 * z + time * 0.65)
  const angle = 0.28 + Math.sin(time * 0.32) * (0.18 + e * 0.18)
  const x4 = x * radius * Math.cos(angle) - w * Math.sin(angle)
  const w4 = x * radius * Math.sin(angle) + w * Math.cos(angle)
  const angleY = Math.sin(time * 0.27) * 0.35
  const y4 = y * radius * Math.cos(angleY) - w4 * Math.sin(angleY)
  const w5 = y * radius * Math.sin(angleY) + w4 * Math.cos(angleY)
  const perspective = 3 / (3 - w5)
  const twist = (0.14 + e * 0.4) * Math.sin(y * 2.5 - time * 0.5)
  return [
    (x4 * Math.cos(twist) - z * radius * Math.sin(twist)) * perspective,
    y4 * perspective,
    (x4 * Math.sin(twist) + z * radius * Math.cos(twist)) * perspective
  ]
}
