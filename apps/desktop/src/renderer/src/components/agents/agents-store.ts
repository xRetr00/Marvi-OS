/**
 * One live view of the sub-agents for the whole window.
 *
 * The status bar, every chat card and the voice card read the same atom, so
 * three surfaces cost one waiting request rather than three timers. It runs
 * only while something is subscribed (`onMount`), and follows the Gateway's
 * revision long-poll: a request waits until something changes, then the next
 * one is armed at once. Failures back off, as the computer poll does.
 */

import { useStore } from '@nanostores/react'
import { atom, onMount } from 'nanostores'
import { useEffect, useState } from 'react'

import type { AgentJob, AgentsFeed } from '../../../../shared/agents'

const RETRY = 5_000
const OFF = 30_000

export const $agents = atom<AgentsFeed | null>(null)

onMount($agents, () => {
  let alive = true
  let timer: ReturnType<typeof setTimeout>
  let revision: number | undefined
  let cooling = RETRY
  const refresh = async (): Promise<void> => {
    let next = 0
    try {
      const answer = await window.marvi?.getAgents?.(revision)
      if (!answer) throw new Error('Gateway unavailable')
      if (alive) $agents.set(answer)
      revision = answer.revision
      cooling = RETRY
    } catch {
      revision = undefined
      cooling = Math.min(cooling * 2, OFF)
      next = cooling
    } finally {
      if (alive) timer = setTimeout(() => void refresh(), next)
    }
  }
  void refresh()
  return () => {
    alive = false
    clearTimeout(timer)
  }
})

export function jobById(feed: AgentsFeed | null, id: string): AgentJob | null {
  return feed?.jobs.find((job) => job.id === id) ?? null
}

export function liveJobs(feed: AgentsFeed | null): AgentJob[] {
  return (feed?.jobs ?? []).filter(
    (job) => job.state === 'running' || job.state === 'awaiting_approval'
  )
}

/** A job id, for a card that has only the job's receipt. */
export function useAgentJob(id: string | undefined): AgentJob | null | undefined {
  const feed = useStore($agents)
  const listed = id ? jobById(feed, id) : null
  const [fetched, setFetched] = useState<AgentJob | null | undefined>(undefined)
  const revision = feed?.revision
  useEffect(() => {
    // Older than the feed's recent list: ask for it directly, once per change.
    if (!id || listed || revision === undefined) return
    let alive = true
    void window.marvi
      ?.getAgentJob?.(id)
      .then((answer) => {
        if (alive) setFetched(answer ?? null)
      })
      .catch(() => {
        if (alive) setFetched(null)
      })
    return () => {
      alive = false
    }
  }, [id, listed, revision])
  if (!id) return undefined
  if (listed) return listed
  if (!feed) return undefined
  return fetched
}

/**
 * The receipt `delegate` returned, however it arrived: an object from the
 * voice bridge, or the enveloped JSON text a chat tool row stores.
 */
export function receiptOf(result: unknown): {
  id?: string
  name?: string
  agent?: string
  ok?: boolean
  detail?: string
} {
  if (result && typeof result === 'object') return result as Record<string, string>
  if (typeof result !== 'string') return {}
  const start = result.indexOf('{')
  const end = result.lastIndexOf('}')
  if (start >= 0 && end > start) {
    try {
      return JSON.parse(result.slice(start, end + 1)) as Record<string, string>
    } catch {
      // Fall through to picking the fields out.
    }
  }
  const pick = (key: string): string | undefined =>
    new RegExp(`"${key}"\\s*:\\s*"([^"]*)"`).exec(result)?.[1]
  return { id: pick('id'), name: pick('name'), agent: pick('agent') }
}
