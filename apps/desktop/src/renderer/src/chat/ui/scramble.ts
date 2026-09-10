/**
 * The settling-text effect on Marvi's activity line.
 *
 * The label changes mid-turn -- "Marvi is thinking" becomes "Marvi is using
 * web search" and back -- and a hard swap reads as a glitch. Scrambling into
 * the new words makes the change look like the same process continuing, which
 * is what it is.
 *
 * The glyph set is Marvi's own: box-drawing and block characters, the same
 * vocabulary as the braille spinner and the context meter, rather than the
 * random-latin churn most scramble effects use. Latin noise reads as broken
 * text; block noise reads as a readout resolving.
 */

import { useEffect, useState } from 'react'

/** Marvi's furniture, not random letters. */
const GLYPHS = '▁▂▃▄▅▆▇█▓▒░╱╲┃┊·'

/** One frame: the first `revealed` characters settled, the rest still noise. */
export function scrambleFrame(
  text: string,
  revealed: number,
  pick: () => number = Math.random
): string {
  if (revealed >= text.length) return text
  let out = ''
  for (let index = 0; index < text.length; index += 1) {
    const settled = text[index]
    if (index < revealed) {
      out += settled
      continue
    }
    // Spaces stay spaces so the word shape holds while the letters resolve --
    // without this the line looks like one long bar rather than a sentence.
    out += settled === ' ' ? ' ' : GLYPHS[Math.floor(pick() * GLYPHS.length) % GLYPHS.length]
  }
  return out
}

/** How fast the text settles. Two characters a frame at ~30ms. */
export const STEP_MS = 30
export const PER_STEP = 2

/** A deterministic stand-in for `Math.random`, seeded per frame.
 *
 * Deterministic so the frame can be computed while rendering: a `Math.random`
 * call there produces a different string every paint, so the same frame
 * flickers between renders and React cannot treat the output as stable. Seeded
 * by the reveal count, successive frames still look unrelated.
 */
export function seeded(seed: number): () => number {
  let state = (seed + 1) * 2654435761
  return () => {
    state ^= state << 13
    state ^= state >>> 17
    state ^= state << 5
    return Math.abs(state % 1000) / 1000
  }
}

function stillness(): boolean {
  return (
    typeof window !== 'undefined' &&
    Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
  )
}

/**
 * `text`, arriving as if it were being tuned in.
 *
 * Returns the finished string immediately when the viewer asked for reduced
 * motion. The reset when `text` changes happens during render rather than in
 * an effect: an effect would paint the previous label once before the new one
 * started settling, so switching from "thinking" to "using web search" would
 * flash the old words first.
 */
export function useScramble(text: string): string {
  const [revealed, setRevealed] = useState(0)
  const [source, setSource] = useState(text)
  if (source !== text) {
    setSource(text)
    setRevealed(0)
  }

  useEffect(() => {
    if (stillness()) return
    const timer = window.setInterval(() => setRevealed((count) => count + PER_STEP), STEP_MS)
    return () => window.clearInterval(timer)
  }, [text])

  if (stillness()) return text
  return scrambleFrame(text, revealed, seeded(revealed))
}
