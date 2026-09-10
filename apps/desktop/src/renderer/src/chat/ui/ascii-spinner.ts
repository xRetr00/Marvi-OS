/**
 * Claude Code's thinking animation: the frames and the cadence.
 *
 * Separate from the component so this file exports no React elements -- the
 * frame order is the only part worth testing, and testing it should not need
 * a renderer.
 */

/** Smallest to largest. Index order is the animation order. */
export const SPINNER_FRAMES = ['·', '✢', '✳', '✶', '✽'] as const

/** Roughly Claude Code's cadence: fast enough to feel alive, slow enough to read. */
export const FRAME_MS = 120

/**
 * Forward then back, without repeating either end.
 *
 * `[0,1,2,3,4,3,2,1]` rather than `[0..4,4..0]`: holding the first and last
 * frame for two ticks makes the pulse hesitate at both extremes. A sequence
 * that only runs forward snaps from the largest glyph straight back to a dot
 * on every cycle, which reads as a stutter rather than as breathing.
 */
export function pulseSequence(length: number): number[] {
  const forward = Array.from({ length }, (_, index) => index)
  return [...forward, ...forward.slice(1, -1).reverse()]
}

export const SEQUENCE = pulseSequence(SPINNER_FRAMES.length)

/** The glyph for a given tick. Pure, so the component stays trivial. */
export function frameAt(tick: number): string {
  return SPINNER_FRAMES[SEQUENCE[tick % SEQUENCE.length]]
}
