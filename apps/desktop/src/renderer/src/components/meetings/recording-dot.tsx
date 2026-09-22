import { Tr } from '../../store/locale'
/**
 * The indicator: Marvi is recording a meeting, and you can see that she is.
 *
 * In the status bar rather than behind a page, and for the whole session
 * rather than at the start of it. A machine that can record a room without
 * saying so is a different product, and this is the difference -- so it polls
 * even when the Meetings page is nowhere near the screen, and it says how long
 * it has been going, because "still recording" is the thing people forget.
 *
 * It also says whether each side is being *heard*. Recording with a muted
 * microphone looks exactly like recording, right up until the transcript comes
 * back with one voice in it.
 */
import { useEffect, useState } from 'react'
import { Disc } from 'lucide-react'

import type { RecordingNow } from '../../../../shared/runtime'

/** How often the indicator asks. Slow: it is a light on a wall, not a stream. */
const EVERY_MS = 3_000

export function RecordingDot({ onOpen }: { onOpen: () => void }): React.JSX.Element | null {
  const [now, setNow] = useState<RecordingNow | null>(null)

  useEffect(() => {
    let alive = true
    const look = async (): Promise<void> => {
      const seen = await window.marvi?.getMeetingNow()
      if (alive) setNow(seen ?? null)
    }
    void look()
    const timer = window.setInterval(() => void look(), EVERY_MS)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [])

  if (!now?.recording) return null

  const minutes = Math.floor((now.seconds ?? 0) / 60)
  const seconds = Math.floor((now.seconds ?? 0) % 60)
  const deaf = now.hearing_you === false && now.hearing_them === false

  return (
    <button
      aria-label={`Recording a meeting, ${minutes} minutes ${seconds} seconds. Open Meetings.`}
      className="status-item status-recording"
      onClick={onOpen}
      type="button"
    >
      <Disc aria-hidden="true" className="status-recording-dot" />
      <span>
        {minutes}:{String(seconds).padStart(2, '0')}
      </span>
      {/* Said here rather than discovered in the transcript afterwards. */}
      {deaf ? (
        <span className="status-recording-deaf">
          <Tr text={'no sound'} />
        </span>
      ) : null}
    </button>
  )
}
