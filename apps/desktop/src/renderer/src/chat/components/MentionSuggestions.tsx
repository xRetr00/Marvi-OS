import { t } from '../../store/locale'
/**
 * Workspace files matching the `@…` being typed.
 *
 * Its own component, not part of `Composer`: the composer's callbacks are
 * memoized and the React compiler gives up on the whole component when an
 * effect it cannot follow is added beside them. A child that owns the search
 * keeps that boundary, and keeps the composer about the composer.
 *
 * Typing the path exactly is what this saves. The Gateway resolves whatever is
 * actually sent, so a mention nobody completed here still works.
 */
import { useEffect, useState } from 'react'

import { completeMention, trailingMention } from '../mention'

/** How long after the last keystroke the search runs. */
const SETTLE_MS = 120
const MOST = 6

export function MentionSuggestions({
  text,
  active,
  onPick
}: {
  text: string
  /** False while the field is unfocused, so the list does not hang around. */
  active: boolean
  onPick: (next: string) => void
}): React.JSX.Element | null {
  const [found, setFound] = useState<string[]>([])
  const mention = active ? trailingMention(text) : null
  const query = mention?.query ?? null

  useEffect(() => {
    if (query === null) return
    let alive = true
    const timer = window.setTimeout(async () => {
      const files = (await window.marvi?.searchWorkspaceFiles(query)) ?? []
      if (alive) setFound(files.slice(0, MOST))
    }, SETTLE_MS)
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [query])

  if (!mention || found.length === 0) return null

  return (
    <ul className="chat-mentions" aria-label={t('Workspace files')}>
      {found.map((path) => (
        <li key={path}>
          <button
            onMouseDown={(event) => {
              // Mouse *down*: the field loses focus on click, which hides this
              // list before a click event would ever land.
              event.preventDefault()
              onPick(completeMention(text, mention, path))
            }}
            type="button"
          >
            {path}
          </button>
        </li>
      ))}
    </ul>
  )
}
