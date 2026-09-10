/**
 * The polling and the one decision behind the asking card.
 *
 * Split out so `asking-card.tsx` exports only components: a file that mixes
 * components with hooks and helpers loses fast refresh, and this is the file
 * whose card is on screen while somebody is typing an answer into it.
 */

import { useEffect, useState } from 'react'

import type { Question } from '../../../shared/asking'

/** How often to ask the Gateway whether there is a question waiting.
 *
 * Slow, and slower still when the window is hidden. The computer island polled
 * every 250ms for the life of the window and put 1,485 refused requests in the
 * log in under seven minutes; a question box has no reason to be quicker than
 * a person can read. */
const NORMAL = 4_000
const HIDDEN = 30_000

export function useAsking(): Question | null {
  const [waiting, setWaiting] = useState<Question | null>(null)
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    let cooling = NORMAL
    const refresh = async (): Promise<void> => {
      let next = NORMAL
      try {
        const answer = await window.marvi?.getAsking?.()
        if (!answer) throw new Error('Gateway unavailable')
        // One at a time. Two boxes for two questions is a form, and a form is
        // the thing this exists instead of.
        if (alive) setWaiting(answer.waiting?.[0] ?? null)
        cooling = NORMAL
      } catch {
        if (alive) setWaiting(null)
        cooling = Math.min(cooling * 2, HIDDEN)
        next = cooling
      } finally {
        if (alive)
          timer = setTimeout(
            () => void refresh(),
            typeof document !== 'undefined' && document.hidden ? HIDDEN : next
          )
      }
    }
    void refresh()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [])
  return waiting
}

/** What will actually be sent, or empty when there is nothing to send.
 *
 * Pulled out of the component because it is the only decision here worth
 * testing on its own, and the desktop suite renders to static markup -- there
 * is no DOM to type into.
 *
 * Whitespace is not an answer. A box holding three spaces that reports itself
 * answered is the worst of the outcomes: Marvi files nothing, marks the
 * question settled, and never asks again.
 */
export function readyToSend(answer: string): string {
  return answer.trim()
}
