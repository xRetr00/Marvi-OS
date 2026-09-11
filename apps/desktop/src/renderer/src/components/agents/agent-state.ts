/**
 * What a sub-agent job's state is called on screen, and what is shown for it.
 *
 * One table, used by the status bar, the chat card and the voice card, so
 * "Stalled" cannot be "Failed" in one place and "Timed out" in another.
 *
 * The state always comes from the Gateway. Codex and Claude Code both shipped
 * cards stuck on "running" after their job ended, because the card decided for
 * itself; here a card only ever renders what the feed last said, and a job the
 * feed no longer knows is `lost`, never still working.
 */

import type { AgentJob } from '../../../../shared/agents'

export type AgentTone = 'working' | 'waiting' | 'done' | 'failed' | 'stopped' | 'lost'

export interface AgentStatus {
  label: string
  tone: AgentTone
  live: boolean
}

export function agentStatus(job: Pick<AgentJob, 'state' | 'exit_reason'> | null): AgentStatus {
  if (!job) return { label: 'Lost when Marvi restarted', tone: 'lost', live: false }
  switch (job.state) {
    case 'running':
      return { label: 'Working', tone: 'working', live: true }
    case 'awaiting_approval':
      return { label: 'Needs your approval', tone: 'waiting', live: true }
    case 'completed':
      return job.exit_reason === 'max_rounds'
        ? { label: 'Finished at step limit', tone: 'done', live: false }
        : { label: 'Finished', tone: 'done', live: false }
    case 'interrupted':
      return { label: 'Stopped', tone: 'stopped', live: false }
    case 'failed':
      return job.exit_reason === 'stalled'
        ? { label: 'Stalled', tone: 'failed', live: false }
        : { label: 'Failed', tone: 'failed', live: false }
    default:
      return { label: 'Unknown', tone: 'lost', live: false }
  }
}

/**
 * The avatar seed. Built-ins by agent key, so Harvi is the same face every
 * run; a worker by its generated name, so each run looks like who it is.
 */
export function avatarSeed(agent: string, name: string, namedPerJob: boolean): string {
  return namedPerJob ? `${agent}:${name}` : agent
}

/** `1m 04s`, `12s`. Seconds only while it is short. */
export function elapsed(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds))
  if (whole < 60) return `${whole}s`
  const minutes = Math.floor(whole / 60)
  return `${minutes}m ${String(whole % 60).padStart(2, '0')}s`
}
