/**
 * Which finished sub-agent jobs this conversation still has to hear about.
 *
 * A chat turn only happened when the owner sent one, so Marvi said "Jarvi's on
 * it", the card turned to FINISHED, and nothing else was ever said. The window
 * now asks the Gateway for a report turn (`resume_job`) for each job a
 * `delegate` call in this thread started, once it has ended and once only. The
 * Gateway stores the report as a background note, which is how "once" is
 * remembered across restarts, and never shows it as something the owner said.
 */

import type { AgentsFeed } from '../../../shared/agents'
import { receiptOf } from '../components/agents/agents-store'
import type { ChatMessage } from './types'

/** The tools whose result is a sub-agent job. */
const DELEGATING = new Set(['delegate', 'delegate_to_coder'])

/** A report note the Gateway stored for the model, not for the window. */
export function isBackground(message: ChatMessage): boolean {
  return message.meta?.background === 'job_report'
}

/** Jobs this thread has already been told about. */
export function reportedJobs(messages: readonly ChatMessage[]): Set<string> {
  return new Set(
    messages
      .filter(isBackground)
      .map((message) => String(message.meta?.job ?? ''))
      .filter(Boolean)
  )
}

/** Jobs started from this thread, by id, in the order they were started. */
export function delegatedJobs(messages: readonly ChatMessage[]): string[] {
  const ids: string[] = []
  for (const message of messages) {
    for (const part of message.parts ?? []) {
      if (part.type !== 'tool' || !DELEGATING.has(part.name)) continue
      const id = receiptOf(part.content).id
      if (id && !ids.includes(id)) ids.push(id)
    }
  }
  return ids
}

/**
 * The next job to report: started here, ended according to the feed, and not
 * yet reported. A job the feed does not list (older, or lost to a restart) is
 * left alone -- there is nothing true to say about it.
 */
export function nextJobToReport(
  messages: readonly ChatMessage[],
  reported: ReadonlySet<string>,
  feed: AgentsFeed | null,
  skip: ReadonlySet<string> = new Set()
): string | undefined {
  if (!feed) return undefined
  return delegatedJobs(messages).find((id) => {
    if (reported.has(id) || skip.has(id)) return false
    const job = feed.jobs.find((one) => one.id === id)
    return Boolean(job && job.state !== 'running' && job.state !== 'awaiting_approval')
  })
}
