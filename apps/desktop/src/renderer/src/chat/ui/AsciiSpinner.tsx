/**
 * Claude Code's thinking animation, in the chat page.
 *
 * Five Unicode glyphs -- interpunct, four-teardrop, eight-spoked, six-pointed,
 * heavy-teardrop -- played forward and then back, so the mark appears to swell
 * and settle rather than snap back to a dot. The reversal is why it reads as
 * breathing: a plain forward loop jumps from the biggest glyph to the smallest
 * every cycle and reads as a stutter.
 *
 * The elapsed seconds beside it are the other half of the point. A spinner
 * says "something is happening"; a spinner with a clock says "and it has been
 * happening for eleven seconds", which is the number somebody actually needs
 * before deciding whether to wait or press stop.
 */

import { useEffect, useState } from 'react'

/** Smallest to largest. Index order is the animation order. */
export const SPINNER_FRAMES = ['·', '✢', '✳', '✶', '✽'] as const

/**
 * Forward then back, without repeating either end.
 *
 * `[0,1,2,3,4,3,2,1]` rather than `[0..4,4..0]`: holding the first and last
 * frame for two ticks makes the pulse hesitate at both extremes.
 */
export function pulseSequence(length: number): number[] {
  const forward = Array.from({ length }, (_, index) => index)
  return [...forward, ...forward.slice(1, -1).reverse()]
}

const SEQUENCE = pulseSequence(SPINNER_FRAMES.length)

/** Roughly Claude Code's cadence: fast enough to feel alive, slow enough to read. */
const FRAME_MS = 120

export function useSpinnerFrame(active: boolean): string {
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!active) return
    // Reduced motion gets the largest glyph, held still. The label and the
    // clock still say what is happening, so nothing is lost but the movement.
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    const timer = window.setInterval(() => setTick((value) => value + 1), FRAME_MS)
    return () => window.clearInterval(timer)
  }, [active])

  if (!active) return SPINNER_FRAMES[0]
  return SPINNER_FRAMES[SEQUENCE[tick % SEQUENCE.length]]
}

/** Whole seconds since `startedAt`, ticking once a second. */
export function useElapsedSeconds(active: boolean, startedAt: number): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!active) return
    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), 1_000)
    return () => window.clearInterval(timer)
  }, [active, startedAt])

  return Math.max(0, Math.floor((now - startedAt) / 1000))
}

export function AsciiSpinner({
  active,
  label = 'Marvi is thinking',
  startedAt
}: {
  active: boolean
  label?: string
  startedAt: number
}): React.JSX.Element | null {
  const glyph = useSpinnerFrame(active)
  const seconds = useElapsedSeconds(active, startedAt)
  if (!active) return null

  return (
    <div className="chat-ascii-spinner" role="status">
      {/* The glyph is decoration; the label is the announcement. A screen
          reader reading five asterisks a second would be unusable. */}
      <span aria-hidden="true" className="chat-ascii-glyph">
        {glyph}
      </span>
      <span className="chat-ascii-label">{label}</span>
      <span className="chat-ascii-elapsed">{seconds}s</span>
      <span className="chat-ascii-hint">esc to interrupt</span>
    </div>
  )
}
