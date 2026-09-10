/**
 * Marvi's spinner. One frame set, everywhere.
 *
 * These are the frames the Marvi Agent TUI uses, so the desktop shell and the
 * terminal read as the same program. It replaced a table of braille, orbit and
 * scan animations from `unicode-animations`: every call site asked for
 * `braille` anyway, so the table was a naming layer over a single choice, and
 * the braille dots were a texture rather than a mark -- they read as static
 * beside Marvi's own typography.
 *
 * The asterisk grows from a point through progressively heavier stars and back
 * down, so it pulses rather than rotating. That is the same shape as the
 * activity language everywhere else here: something opening, not something
 * spinning in place.
 */
import { useEffect, useRef } from 'react'

/**
 * Each frame carries U+FE0E, the text presentation selector.
 *
 * Without it several of these are rendered as colour emoji -- so the spinner
 * changed size, baseline and hue between frames, and jittered the line it sat
 * in. The selector forces the monochrome text glyph, which is what a spinner
 * beside a sentence needs to be.
 */
export const MARVI_SPINNER_FRAMES = [
  '·︎',
  '✲︎',
  '✵︎',
  '✶︎',
  '✷︎',
  '✸︎',
  '✹︎',
  '✺︎',
  '✻︎',
  '✼︎',
  '✽︎',
  '✾︎',
  '✿︎'
] as const

/** Fast enough to read as motion, slow enough that the shape registers. */
export const FRAME_INTERVAL_MS = 80

interface GlyphSpinnerProps {
  ariaLabel?: string
  className?: string
}

export function GlyphSpinner({
  ariaLabel = 'Loading',
  className
}: GlyphSpinnerProps): React.JSX.Element {
  const glyphRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    const glyph = glyphRef.current
    if (!glyph) return undefined
    // Reduced motion keeps the mark, loses the movement: the frame that reads
    // most clearly as "busy" rather than as a full stop.
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return undefined

    let frame = 0
    const timer = window.setInterval(() => {
      frame = (frame + 1) % MARVI_SPINNER_FRAMES.length
      // Written straight to the node rather than through state: this ticks
      // twelve times a second beside streaming text, and re-rendering the
      // whole message for one character is work nobody sees.
      glyph.textContent = MARVI_SPINNER_FRAMES[frame]
    }, FRAME_INTERVAL_MS)

    return () => window.clearInterval(timer)
  }, [])

  return (
    <span
      aria-label={ariaLabel}
      className={`glyph-spinner${className ? ` ${className}` : ''}`}
      ref={glyphRef}
      role="status"
    >
      {MARVI_SPINNER_FRAMES[0]}
    </span>
  )
}
