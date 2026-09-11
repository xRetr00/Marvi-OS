/** The Gateway's `/agents` feed: the sub-agent roster and their jobs. */

export type AgentJobState =
  | 'running'
  | 'awaiting_approval'
  | 'completed'
  | 'failed'
  | 'interrupted'

export interface AgentProfile {
  key: string
  name: string
  description: string
  when_to_use: string
  /** A worker takes a new name each run, so its avatar is seeded per job. */
  named_per_job: boolean
}

export interface AgentJob {
  id: string
  agent: string
  name: string
  mode: string
  task: string
  state: AgentJobState
  /** completed | max_rounds | stopped | stalled | error */
  exit_reason: string
  summary: string
  progress: string
  seconds: number
  started_at: number
  finished_at: number | null
  tokens: number
  detail: string
  action?: string
}

export interface AgentEvent {
  at: number
  kind: 'said' | 'tool' | 'approval' | 'end'
  text: string
  outcome?: 'running' | 'ok' | 'failed'
  state?: string
  reason?: string
}

export interface AgentJobDetail extends AgentJob {
  events: AgentEvent[]
  todos: { content: string; status: string }[]
  revision: number
}

export interface AgentsFeed {
  revision: number
  agents: AgentProfile[]
  jobs: AgentJob[]
}
