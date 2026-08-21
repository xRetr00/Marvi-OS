/**
 * A deterministic displacement shared by the entire lattice. Nearby points
 * receive nearby values, so the sphere folds like a membrane rather than
 * fizzing like unrelated particles.
 */
export function coherentWaveScale(
  point: readonly [number, number, number],
  phase: number,
  energy: number
): number {
  const [x, y, z] = point
  const amount = Math.max(0, Math.min(1, energy))
  if (amount === 0) return 1
  const longitude = Math.atan2(z, x)
  const latitude = Math.asin(Math.max(-1, Math.min(1, y)))
  const broadWave = Math.sin(latitude * 4.5 - phase)
  const diagonalWave = Math.sin(longitude * 2 + latitude * 1.5 - phase * 0.72)
  return 1 + amount * (broadWave * 0.105 + diagonalWave * 0.035)
}
