/**
 * A deterministic displacement shared by the entire lattice. Nearby points
 * receive nearby values, so the sphere folds like a membrane rather than
 * fizzing like unrelated particles.
 *
 * `energy` scales the fold, and it never scales it to nothing. Returning a
 * flat 1 at zero energy made the orb completely rigid whenever nobody was
 * speaking -- which is most of the time -- so the Voice page showed a frozen
 * ball rather than something idling. A resting swell says Marvi is running;
 * voice then pushes real amplitude through it.
 */
/** The fold that remains when the room is silent. */
export const REST = 0.16

export function coherentWaveScale(
  point: readonly [number, number, number],
  phase: number,
  energy: number
): number {
  const [x, y, z] = point
  // Small enough to read as breathing rather than motion, large enough that
  // the surface is visibly alive at rest.
  const amount = REST + (1 - REST) * Math.max(0, Math.min(1, energy))
  const longitude = Math.atan2(z, x)
  const latitude = Math.asin(Math.max(-1, Math.min(1, y)))
  const broadWave = Math.sin(latitude * 4.5 - phase)
  const diagonalWave = Math.sin(longitude * 2 + latitude * 1.5 - phase * 0.72)
  return 1 + amount * (broadWave * 0.105 + diagonalWave * 0.035)
}
