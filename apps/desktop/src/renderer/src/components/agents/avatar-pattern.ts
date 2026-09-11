/**
 * The avatar's deterministic pattern, apart from its canvas so it can be
 * tested without one: the same seed must always give the same face, or Harvi
 * would look like somebody else after every restart.
 */

export const GRID_SIZE = 6

/** Max hue spread from base — wider for richer color variation */
const HUE_SPREAD = 45

/** Simple deterministic hash from a string */
export const hashSeed = (str: string): number => {
  let hash = 0
  for (const char of str) {
    hash = ((hash << 5) - hash + char.charCodeAt(0)) | 0
  }
  return Math.abs(hash)
}

/** Seeded PRNG (mulberry32) */
export const createRng = (seed: number): (() => number) => {
  let state = seed
  return () => {
    state = (state + 0x6d_2b_79_f5) | 0
    let t = Math.imul(state ^ (state >>> 15), 1 | state)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296
  }
}

export type HSL = [hue: number, saturation: number, lightness: number]

/** Derive a 3-color palette within the same hue family */
export const generatePalette = (hash: number): [HSL, HSL, HSL] => {
  const rng = createRng(hash)
  const baseHue = rng() * 360
  const sat = 75 + rng() * 20 // 75-95%

  return [
    [baseHue, sat, 55 + rng() * 10],
    [(baseHue - HUE_SPREAD + rng() * HUE_SPREAD * 2) % 360, sat - 5 + rng() * 10, 40 + rng() * 15],
    [(baseHue - HUE_SPREAD + rng() * HUE_SPREAD * 2) % 360, sat - 10 + rng() * 15, 60 + rng() * 15]
  ]
}

export type Cell = {
  colorIndex: number
  phase: number
  brightness: number
  sparklePhase: number
}

/** Build a grid with per-cell metadata */
export const generateGrid = (hash: number): Cell[][] => {
  const rng = createRng(hash + 1)
  const grid: Cell[][] = []
  for (let y = 0; y < GRID_SIZE; y++) {
    grid[y] = []
    for (let x = 0; x < GRID_SIZE; x++) {
      grid[y][x] = {
        brightness: 0.3 + rng() * 0.7,
        colorIndex: Math.floor(rng() * 3),
        phase: rng() * Math.PI * 2,
        sparklePhase: rng() * Math.PI * 2
      }
    }
  }
  return grid
}
