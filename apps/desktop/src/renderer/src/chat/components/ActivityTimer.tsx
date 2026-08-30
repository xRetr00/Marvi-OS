import { useEffect, useState } from 'react'

import { activitySeconds, formatActivityTime } from '../activity-time'

export function ActivityTimer({
  active,
  startedAt
}: {
  active: boolean
  startedAt: string
}): React.JSX.Element {
  const [now, setNow] = useState(Date.now)

  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setNow(Date.now()), 1_000)
    return () => window.clearInterval(timer)
  }, [active])

  return (
    <span className="chat-activity-time">
      {formatActivityTime(activitySeconds(startedAt, now))}
    </span>
  )
}
