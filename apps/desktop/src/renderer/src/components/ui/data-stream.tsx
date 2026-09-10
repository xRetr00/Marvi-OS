/**
 * A log, as something you can watch rather than something you scroll.
 *
 * Marvi produces a lot of lines that are only interesting live — wake-word
 * detections and their scores, tool calls, the mind's decisions, a browser
 * session's steps. A `<pre>` full of them is unreadable at a glance and a
 * table is too heavy for a feed, so this is the middle: one line per event,
 * a dot carrying the severity, a timestamp, and the newest at the bottom.
 *
 * Adapted from a Tailwind/shadcn component. Three things changed on the way
 * in, and each one is a behaviour rather than a paint job:
 *
 * **New entries no longer restart the reveal.** The original keyed its
 * staggered animation on `entries.length` and reset the counter to zero
 * whenever it changed, so a stream that gains a line every few seconds spends
 * its life replaying from the top and never shows the newest. Here the
 * revealed count only ever climbs, and the effect that drives it does not
 * depend on the array identity.
 *
 * **It stops auto-scrolling once you scroll up.** A live feed that yanks you
 * back to the bottom while you are reading is unusable, which is the one
 * thing people actually do with a log.
 *
 * **The colours are the app's**, not the palette the original hardcoded. The
 * ready/warning/danger tones already exist for the health dots, so a warning
 * here is the same amber as a warning anywhere else in Marvi.
 */
import { useEffect, useRef, useState } from 'react'
import './data-stream.css'

export type StreamTone = 'info' | 'success' | 'warning' | 'error'

export interface StreamEntry {
  /** Already formatted. The stream does not know your timezone or your taste. */
  timestamp?: string
  text: string
  tone?: StreamTone
  /** Right-aligned, for a number that wants comparing down the column. */
  hint?: string
}

/** How long between one line appearing and the next, in milliseconds.
 *
 * 300ms was the original. That reads well for four lines and is a wait for
 * twenty, so it only applies to the first paint; anything arriving after that
 * appears at once, because a live line held back for a third of a second is a
 * live line arriving late. */
const REVEAL_MS = 60

export function DataStream({
  entries,
  title = 'DATA STREAM',
  maxVisible = 8,
  streaming = true,
  empty = 'Nothing yet.',
  className = ''
}: {
  entries: StreamEntry[]
  title?: string
  /** Rows to show before scrolling. Height, not a limit on entries. */
  maxVisible?: number
  /** Whether to show the live pulse. False for a finished or paused feed. */
  streaming?: boolean
  empty?: string
  className?: string
}): React.JSX.Element {
  const [shown, setShown] = useState(0)
  const scroller = useRef<HTMLDivElement>(null)
  const following = useRef(true)
  const total = entries.length

  // Derived, not stored, so a list that shrinks -- cleared, or filtered --
  // needs no effect to correct the counter. Setting state from an effect to
  // fix state is a render you can see.
  const visible = Math.min(shown, total)

  // Climbs towards `total` and never resets. Reading the count from the
  // updater rather than from a dependency is what lets the timer keep running
  // across renders without restarting the reveal from the top.
  useEffect(() => {
    if (visible >= total) return
    const timer = setTimeout(() => setShown((so_far) => Math.min(so_far, total) + 1), REVEAL_MS)
    return () => clearTimeout(timer)
  }, [visible, total])

  useEffect(() => {
    const box = scroller.current
    if (box && following.current) box.scrollTop = box.scrollHeight
  }, [visible])

  return (
    <div className={`stream ${className}`.trim()} data-slot="data-stream">
      <div className="stream-head">
        {streaming ? <span aria-hidden="true" className="stream-live" /> : null}
        <span className="stream-title">{title}</span>
        <span className="stream-count">
          {visible}/{total}
        </span>
      </div>
      <div
        aria-label={title}
        aria-live="polite"
        className="stream-body"
        onScroll={(event) => {
          const box = event.currentTarget
          // Within a line of the bottom counts as following; scrolling up
          // anywhere else stops the feed chasing you.
          following.current = box.scrollHeight - box.scrollTop - box.clientHeight < 28
        }}
        ref={scroller}
        role="log"
        style={{ maxHeight: maxVisible * 26 }}
      >
        {total === 0 ? (
          <p className="stream-empty">{empty}</p>
        ) : (
          entries.slice(0, visible).map((entry, index) => (
            <div className="stream-row" key={`${entry.timestamp ?? ''}-${index}`}>
              <span aria-hidden="true" className={`stream-dot tone-${entry.tone ?? 'info'}`} />
              {entry.timestamp ? <span className="stream-when">{entry.timestamp}</span> : null}
              <span className={`stream-text tone-${entry.tone ?? 'info'}`}>{entry.text}</span>
              {entry.hint ? <span className="stream-hint">{entry.hint}</span> : null}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
