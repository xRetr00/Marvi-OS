/**
 * DecodeText — the "CONNECTING" scramble-decode effect as a reusable
 * primitive, adapted from the Marvi/Hermes desktop shell (MIT):
 * D:\hermes-agent\apps\desktop\src\components\ui\decode-text.tsx.
 *
 *  - Even-weight mono ascii charset so cycling glyphs never jump width.
 *  - Decode resolves half a character per 45 ms tick.
 *  - The first `prefix` characters NEVER scramble.
 *  - Reduced-motion users get the plain resolved text.
 */
import { useEffect, useState } from 'react'

export const DECODE_SCRAMBLE_CHARS = '/\\|-_=+<>~:*'
const TICK_MS = 45

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
  )
}

function scrambled(tail: string, resolvedCount: number): string {
  return Array.from(tail, (ch, index) =>
    ch === ' ' || index < resolvedCount
      ? ch
      : DECODE_SCRAMBLE_CHARS[(Math.random() * DECODE_SCRAMBLE_CHARS.length) | 0]
  ).join('')
}

export interface DecodeTextProps {
  text: string
  /** Leading character count that stays legible at all times. */
  prefix?: number
  /** Run the decode. When false, renders the plain resolved text. */
  active?: boolean
  className?: string
}

export function DecodeText({
  active = true,
  className,
  prefix = 0,
  text
}: DecodeTextProps): React.JSX.Element {
  const [tick, setTick] = useState(0)
  const reduce = prefersReducedMotion()

  useEffect(() => {
    if (!active || reduce) return undefined
    const timer = window.setInterval(() => setTick((value) => value + 1), TICK_MS)
    return () => window.clearInterval(timer)
  }, [active, reduce])

  if (!active || reduce) return <span className={className}>{text}</span>

  const head = text.slice(0, prefix)
  const tail = text.slice(prefix)
  const resolved = Math.min(tail.length, Math.floor(tick / 2))

  return (
    <span className={className}>
      {head}
      {scrambled(tail, resolved)}
    </span>
  )
}
