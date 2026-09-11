/**
 * Sub-agents on screen: the status-bar roster, the job card Chat and Voice
 * draw when Marvi hands work off, and a job's live transcript.
 *
 * Every state shown comes from the Gateway's `/agents` feed (`$agents`); a
 * card never decides on its own that a job is still running. See
 * `agent-state.ts` for why.
 */

import { useStore } from '@nanostores/react'
import { Bot, ChevronDown, Square } from 'lucide-react'
import { Popover } from 'radix-ui'
import { useEffect, useState } from 'react'

import type { AgentJob, AgentJobDetail, AgentProfile } from '../../../../shared/agents'
import { AgentAvatar } from './agent-avatar'
import { agentStatus, avatarSeed, elapsed, plain } from './agent-state'
import { $agents, liveJobs, receiptOf, useAgentJob } from './agents-store'
import './agents.css'

/** What each built-in is for, in two words, under its name. */
const ROLE: Record<string, string> = {
  harvi: 'Coding',
  jarvi: 'Computer use',
  talos: 'Browser use',
  worker: 'Long jobs',
  // Outside coders Marvi reaches over the Agent Client Protocol.
  claude: 'Outside coder · ACP',
  codex: 'Outside coder · ACP',
  opencode: 'Outside coder · ACP',
  gemini: 'Outside coder · ACP'
}

function profileFor(agent: string, roster: AgentProfile[] | undefined): AgentProfile | undefined {
  return roster?.find((one) => one.key === agent)
}

function seedFor(job: Pick<AgentJob, 'agent' | 'name'>, roster?: AgentProfile[]): string {
  const profile = profileFor(job.agent, roster)
  return avatarSeed(job.agent, job.name, profile?.named_per_job ?? job.agent === 'worker')
}

/** Seconds that keep counting while a job is live, between feed updates. */
function useElapsed(job: AgentJob | null | undefined): string {
  const [now, setNow] = useState(() => Date.now())
  const live = Boolean(job && agentStatus(job).live)
  useEffect(() => {
    if (!live) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [live])
  if (!job) return ''
  const end = job.finished_at ? job.finished_at * 1000 : live ? now : job.started_at * 1000
  return elapsed(job.finished_at || live ? (end - job.started_at * 1000) / 1000 : job.seconds)
}

export function AgentStatusChip({
  job,
  pending
}: {
  job: AgentJob | null | undefined
  pending?: string
}): React.JSX.Element {
  const status = agentStatus(job, pending)
  return (
    <span className={`agent-chip is-${status.tone}`} data-tone={status.tone}>
      {status.live ? <span aria-hidden="true" className="agent-chip-pulse" /> : null}
      {status.label}
    </span>
  )
}

/** One job's steps, list and ending, fetched when opened and kept current. */
export function AgentTranscript({ jobId }: { jobId: string }): React.JSX.Element {
  const feed = useStore($agents)
  const [detail, setDetail] = useState<AgentJobDetail | null | undefined>(undefined)
  const revision = feed?.revision
  useEffect(() => {
    let alive = true
    void window.marvi
      ?.getAgentJob?.(jobId)
      .then((answer) => {
        if (alive) setDetail(answer ?? null)
      })
      .catch(() => {
        if (alive) setDetail(null)
      })
    return () => {
      alive = false
    }
  }, [jobId, revision])
  return <TranscriptView detail={detail} />
}

/** The transcript, given its data -- split for `renderToStaticMarkup` tests. */
export function TranscriptView({
  detail
}: {
  detail: AgentJobDetail | null | undefined
}): React.JSX.Element {
  if (detail === undefined) return <p className="agent-transcript-empty">Loading…</p>
  if (detail === null)
    return <p className="agent-transcript-empty">This job is gone — Marvi restarted since.</p>
  return (
    <div className="agent-transcript">
      <p className="agent-transcript-task">{detail.task}</p>
      {detail.todos.length ? (
        <ul className="agent-todos" aria-label="Its list">
          {detail.todos.map((todo, index) => (
            <li className={`is-${todo.status}`} key={index}>
              <span aria-hidden="true">
                {todo.status === 'completed'
                  ? '[x]'
                  : todo.status === 'in_progress'
                    ? '[>]'
                    : '[ ]'}
              </span>
              {todo.content}
            </li>
          ))}
        </ul>
      ) : null}
      <ol className="agent-events" aria-label="What it did" aria-live="polite">
        {detail.events.map((event, index) => (
          <li className={`agent-event is-${event.kind} is-${event.outcome ?? 'none'}`} key={index}>
            <span aria-hidden="true" className="agent-event-mark">
              {event.kind === 'said'
                ? '›'
                : event.kind === 'approval'
                  ? '?'
                  : event.kind === 'end'
                    ? '■'
                    : event.outcome === 'failed'
                      ? '×'
                      : event.outcome === 'running'
                        ? '…'
                        : '·'}
            </span>
            <span className="agent-event-text">{event.text}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

/**
 * A job, as a card: face, name, what it is doing, and its state.
 *
 * `job` undefined is not known yet (`pending` names why); null means the feed
 * has answered and does not know it -- the Gateway restarted since -- which is
 * said rather than spun on.
 */
export function AgentJobCard({
  job,
  roster,
  fallbackName,
  fallbackAgent,
  fallbackLine,
  pending,
  defaultOpen = false
}: {
  job: AgentJob | null | undefined
  roster?: AgentProfile[]
  fallbackName?: string
  fallbackAgent?: string
  fallbackLine?: string
  pending?: string
  defaultOpen?: boolean
}): React.JSX.Element {
  const [open, setOpen] = useState(defaultOpen)
  const [stopping, setStopping] = useState(false)
  const status = agentStatus(job, pending)
  const agent = job?.agent || fallbackAgent || 'worker'
  const name = job?.name || fallbackName || agent.charAt(0).toUpperCase() + agent.slice(1)
  const time = useElapsed(job)
  const line =
    job?.state === 'awaiting_approval'
      ? job.action
        ? `Wants to run ${job.action}`
        : 'Waiting for your answer'
      : status.live
        ? job?.progress || job?.task || fallbackLine
        : job?.summary || job?.task || fallbackLine
  return (
    <section
      aria-label={`${name}, ${status.label}`}
      className={`agent-card is-${status.tone}`}
      data-agent={agent}
    >
      <button
        aria-expanded={open}
        className="agent-card-head"
        disabled={!job?.id}
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <AgentAvatar
          animated={status.live}
          label={`${name}'s avatar`}
          seed={seedFor({ agent, name }, roster)}
          size={30}
        />
        <span className="agent-card-who">
          <strong>{name}</strong>
          <small>{ROLE[agent] ?? profileFor(agent, roster)?.name ?? agent}</small>
        </span>
        <AgentStatusChip job={job} pending={pending} />
        {time ? <span className="agent-card-time">{time}</span> : null}
        {job?.id ? <ChevronDown aria-hidden="true" className="agent-card-caret" size={14} /> : null}
      </button>
      {line ? <p className="agent-card-line">{plain(line)}</p> : null}
      {open && job?.id ? (
        <div className="agent-card-body">
          <AgentTranscript jobId={job.id} />
          {status.live ? (
            <button
              className="agent-card-stop"
              disabled={stopping}
              onClick={() => {
                setStopping(true)
                void window.marvi?.stopAgentJob?.(job.id).finally(() => setStopping(false))
              }}
              type="button"
            >
              <Square aria-hidden="true" size={11} /> STOP
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}

/** The card a `delegate` call draws in Chat. */
export function DelegateCard({
  args,
  result,
  running
}: {
  args: Record<string, unknown>
  result: unknown
  running: boolean
}): React.JSX.Element {
  const feed = useStore($agents)
  const receipt = receiptOf(result)
  const job = useAgentJob(receipt.id)
  const agent = String(receipt.agent ?? args.agent ?? 'worker')
  if (running) {
    return (
      <AgentJobCard
        fallbackAgent={agent}
        fallbackLine={String(args.task ?? '')}
        fallbackName={agent === 'worker' ? 'A worker' : undefined}
        job={undefined}
        pending="Handing over"
        roster={feed?.agents}
      />
    )
  }
  if (receipt.ok === false || !receipt.id) {
    return (
      <div className="agent-card is-failed agent-card-refused">
        <strong>Could not hand this to {agent}</strong>
        <p className="agent-card-line">{receipt.detail ?? 'The Gateway refused it.'}</p>
      </div>
    )
  }
  return (
    <AgentJobCard
      fallbackAgent={agent}
      fallbackLine={String(args.task ?? '')}
      fallbackName={receipt.name}
      job={job}
      pending="Checking"
      roster={feed?.agents}
    />
  )
}

/** The Voice page's strip: who is working now, and who just finished. */
export function AgentJobsStrip(): React.JSX.Element | null {
  const feed = useStore($agents)
  const live = liveJobs(feed)
  const recent = (feed?.jobs ?? []).filter((job) => !live.includes(job)).slice(0, 2)
  if (!live.length && !recent.length) return null
  return (
    <div className="agent-strip" aria-label="Sub-agents">
      {[...live, ...recent].map((job) => (
        <AgentJobCard job={job} key={job.id} roster={feed?.agents} />
      ))}
    </div>
  )
}

/** The status-bar button and its roster popover. */
export function AgentsStatusItem(): React.JSX.Element {
  const feed = useStore($agents)
  const [open, setOpen] = useState(false)
  const live = liveJobs(feed)
  const waiting = live.some((job) => job.state === 'awaiting_approval')
  return (
    <Popover.Root onOpenChange={setOpen} open={open}>
      <Popover.Trigger asChild>
        <button
          aria-label={
            live.length ? `Sub-agents, ${live.length} working` : 'Sub-agents, none working'
          }
          className={`status-item status-agents${live.length ? ' is-working' : ''}${waiting ? ' is-waiting' : ''}`}
          type="button"
        >
          <Bot aria-hidden="true" size={14} />
          {live.length ? <span className="status-agents-count">{live.length}</span> : null}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          className="agents-panel"
          collisionPadding={12}
          side="top"
          sideOffset={8}
        >
          <AgentsPanel feed={feed} />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

/** The popover's contents, given the feed -- split for static-markup tests. */
export function AgentsPanel({ feed }: { feed: ReturnType<typeof $agents.get> }): React.JSX.Element {
  const [chosen, setChosen] = useState<string | null>(null)
  const live = liveJobs(feed)
  const recent = (feed?.jobs ?? []).filter((job) => !live.includes(job)).slice(0, 3)
  if (!feed) return <p className="agents-panel-empty">Sub-agents are not reachable yet.</p>
  return (
    <div className="agents-panel-inner">
      <header className="agents-panel-head">
        <span>SUB-AGENTS</span>
        <small>Marvi hands them work; you talk to Marvi.</small>
      </header>
      <ul className="agents-roster" aria-label="Sub-agents">
        {feed.agents.map((agent) => {
          const working = live.find((job) => job.agent === agent.key)
          const expanded = chosen === agent.key
          return (
            <li key={agent.key}>
              <button
                aria-expanded={expanded}
                className={`agents-roster-row${working ? ' is-working' : ''}`}
                onClick={() => setChosen(expanded ? null : agent.key)}
                type="button"
              >
                <AgentAvatar
                  animated={Boolean(working)}
                  label={`${agent.name}'s avatar`}
                  seed={working ? seedFor(working, feed.agents) : agent.key}
                  size={34}
                />
                <span className="agents-roster-who">
                  <strong>{working && agent.named_per_job ? working.name : agent.name}</strong>
                  <small>{ROLE[agent.key] ?? agent.name}</small>
                </span>
                {working ? <AgentStatusChip job={working} /> : null}
              </button>
              {expanded ? (
                <div className="agents-roster-about">
                  <p>{agent.description}</p>
                  <p className="agents-roster-when">{agent.when_to_use}</p>
                </div>
              ) : null}
            </li>
          )
        })}
      </ul>
      <section className="agents-panel-section" aria-label="Working now">
        <h3>WORKING NOW</h3>
        {live.length ? (
          live.map((job) => <AgentJobCard job={job} key={job.id} roster={feed.agents} />)
        ) : (
          <p className="agents-panel-empty">Nobody is working.</p>
        )}
      </section>
      {recent.length ? (
        <section className="agents-panel-section" aria-label="Recently">
          <h3>RECENTLY</h3>
          {recent.map((job) => (
            <AgentJobCard job={job} key={job.id} roster={feed.agents} />
          ))}
        </section>
      ) : null}
    </div>
  )
}
