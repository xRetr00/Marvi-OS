/**
 * Claude Code's thinking animation, above the prompt.
 *
 * Five Unicode glyphs -- interpunct, four-teardrop, eight-spoked, six-pointed,
 * heavy-teardrop -- played forward and then back, so the mark swells and
 * settles rather than snapping back to a dot.
 *
 * The elapsed seconds beside it are the other half of the point. A spinner
 * says "something is happening"; a spinner with a clock says "and it has been
 * happening for eleven seconds", which is the number somebody actually needs
 * before deciding whether to keep waiting or press stop.
 *
 * It is mounted only while a turn is running, and unmounted when the turn
 * ends. That is what keeps it honest without a reset: a fresh mount starts at
 * zero, so the clock can never show a stale count from the previous turn.
 */

import { useEffect, useState } from 'react'

import { FRAME_MS, SPINNER_FRAMES, frameAt } from './ascii-spinner'

export function AsciiSpinner({
  label = 'Marvi is thinking'
}: {
  label?: string
}): React.JSX.Element {
  const [tick, setTick] = useState(0)
  const [seconds, setSeconds] = useState(0)

  useEffect(() => {
    // Reduced motion gets the largest glyph, held still. The label and the
    // clock still say what is happening, so only the movement is lost.
    const still = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const started = Date.now()
    const clock = window.setInterval(
      () => setSeconds(Math.floor((Date.now() - started) / 1000)),
      1_000
    )
    const frames = still
      ? undefined
      : window.setInterval(() => setTick((value) => value + 1), FRAME_MS)
    return () => {
      window.clearInterval(clock)
      if (frames !== undefined) window.clearInterval(frames)
    }
  }, [])

  const glyph = tick === 0 ? SPINNER_FRAMES[SPINNER_FRAMES.length - 1] : frameAt(tick)

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
