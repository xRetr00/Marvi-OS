import { t } from '../../store/locale'
import { Tr } from '../../store/locale'
/**
 * What the search box finds *inside* conversations.
 *
 * The box filtered thread titles, which answers "which conversation was
 * called that" and not "where did we talk about the hotel" -- and the second
 * is the question people actually have. Titles are auto-named from the first
 * message, so the thing being looked for is usually nowhere in them.
 *
 * Its own component for the same reason as the mention list: the search runs
 * in an effect, and the sessions list around it is memoized.
 */
import { useEffect, useState } from 'react'

import type { ChatMessageMatch } from '../../../../shared/runtime'

/** After the last keystroke. Long enough not to search every letter. */
const SETTLE_MS = 200

/** Below this a search matches half the history and means nothing. */
const SHORTEST = 2

export function MessageMatches({
  query,
  activeId,
  onSelect
}: {
  query: string
  activeId: string
  onSelect: (threadId: string) => void
}): React.JSX.Element | null {
  const [matches, setMatches] = useState<ChatMessageMatch[]>([])
  const words = query.trim()

  useEffect(() => {
    if (words.length < SHORTEST) return
    let alive = true
    const timer = window.setTimeout(async () => {
      const found = (await window.marvi?.searchChatMessages(words)) ?? []
      if (alive) setMatches(found)
    }, SETTLE_MS)
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [words])

  if (words.length < SHORTEST || matches.length === 0) return null

  return (
    <section aria-label={t('Messages')} className="chat-session-group">
      <div className="chat-sessions-label">
        <span>
          <Tr text={'IN MESSAGES'} />
        </span>
        <span>{matches.length}</span>
      </div>
      <ul className="chat-session-list chat-message-matches">
        {matches.map((match) => (
          <li key={`${match.thread_id}-${match.message_id}`}>
            <button
              className={match.thread_id === activeId ? 'is-active' : ''}
              onClick={() => onSelect(match.thread_id)}
              type="button"
            >
              <span className="chat-match-title">
                {match.title}
                {match.archived ? ' · archived' : ''}
              </span>
              <span className="chat-match-snippet">
                {match.role === 'user' ? 'You: ' : 'Marvi: '}
                {match.snippet}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
