/**
 * One-char glyph spinner driven by `unicode-animations` (braille, orbit, scan,
 * ...). Adapted from the the predecessor assistant desktop shell (MIT):
 * the predecessor assistant\apps\desktop\src\components\ui\glyph-spinner.tsx — minus the
 * pane-shell visibility controller, which Marvi OS does not have. Mirrors the
 * spinner the Marvi Agent TUI uses so desktop and terminal read the same.
 */
import { useEffect, useRef } from 'react'
import spinners, { type BrailleSpinnerName as SpinnerName } from 'unicode-animations'

export type { SpinnerName }

interface NormalisedSpinner {
  frames: readonly string[]
  interval: number
}

// Some spinners ship multi-character frames. Pull the first cell so each
// frame fits in one monospace box — matches how the TUI uses them.
const FRAMES_BY_NAME: Record<SpinnerName, NormalisedSpinner> = (() => {
  const out = {} as Record<SpinnerName, NormalisedSpinner>

  for (const name of Object.keys(spinners) as SpinnerName[]) {
    const raw = spinners[name]

    out[name] = {
      frames: raw.frames.map((frame) => [...frame][0] ?? '⠀'),
      interval: raw.interval
    }
  }

  return out
})()

interface GlyphSpinnerProps {
  ariaLabel?: string
  className?: string
  spinner?: SpinnerName
}

export function GlyphSpinner({
  ariaLabel = 'Loading',
  className,
  spinner = 'braille'
}: GlyphSpinnerProps): React.JSX.Element {
  const spin = FRAMES_BY_NAME[spinner] ?? FRAMES_BY_NAME.braille
  const glyphRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    const glyph = glyphRef.current
    if (!glyph) return undefined

    let frame = 0
    glyph.textContent = spin.frames[0]

    const timer = window.setInterval(() => {
      frame = (frame + 1) % spin.frames.length
      glyph.textContent = spin.frames[frame]
    }, spin.interval)

    return () => window.clearInterval(timer)
  }, [spin])

  return (
    <span
      aria-label={ariaLabel}
      className={`glyph-spinner${className ? ` ${className}` : ''}`}
      ref={glyphRef}
      role="status"
    >
      {spin.frames[0]}
    </span>
  )
}
