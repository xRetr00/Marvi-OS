/**
 * One live view of the sub-agents for the whole window.
 *
 * The status bar, every chat card and the voice card read the same atom, so
 * three surfaces cost one waiting request rather than three timers. It runs
 * only while something is subscribed (`onMount`), and follows the Gateway's
 * revision long-poll: a request waits until something changes, then the next
 * one is armed at once. Failures back off, as the computer poll does.
 */

import { atom, onMount } from 'nanostores'

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
