import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { AgentJob, AgentJobDetail, AgentsFeed } from '../../../../shared/agents'
import { groupWork } from '../../chat/ui/group-work'
import { agentStatus, avatarSeed, elapsed } from './agent-state'
import { AgentJobCard, AgentsPanel, receiptOf, TranscriptView } from './agents'
import { generateGrid, generatePalette, hashSeed } from './avatar-pattern'

const job = (overrides: Partial<AgentJob> = {}): AgentJob => ({
  id: 'ab12cd34',
  agent: 'jarvi',
  name: 'Jarvi',
  mode: '',
  task: 'Open Notepad and read its title',
  state: 'running',
  exit_reason: '',
  summary: '',
  progress: 'Reading the window',
  seconds: 12,
  started_at: 1_000,
  finished_at: null,
  tokens: 900,
  detail: '',
  ...overrides
})

const feed: AgentsFeed = {
  revision: 7,
  agents: [
    { key: 'harvi', name: 'Harvi', description: "Marvi's coder.", when_to_use: 'Code.', named_per_job: false },
    { key: 'jarvi', name: 'Jarvi', description: 'Desktop apps.', when_to_use: 'Apps.', named_per_job: false },
    { key: 'worker', name: 'Worker', description: 'Anything long.', when_to_use: 'Jobs.', named_per_job: true }
  ],
  jobs: [job()]
}

describe('avatar pattern', () => {
  it('is the same face for the same seed, and a different one otherwise', () => {
    expect(generatePalette(hashSeed('harvi'))).toEqual(generatePalette(hashSeed('harvi')))
    expect(generateGrid(hashSeed('harvi'))).toEqual(generateGrid(hashSeed('harvi')))
    expect(generatePalette(hashSeed('harvi'))).not.toEqual(generatePalette(hashSeed('jarvi')))
  })

  it('seeds built-ins by key and workers by their run name', () => {
    expect(avatarSeed('harvi', 'Harvi', false)).toBe('harvi')
    expect(avatarSeed('worker', 'Nova', true)).toBe('worker:Nova')
  })
})

describe('agent status', () => {
  it('names every state the Gateway reports, and never guesses', () => {
    expect(agentStatus(job()).label).toBe('Working')
    expect(agentStatus(job({ state: 'awaiting_approval' })).label).toBe('Needs your approval')
    expect(agentStatus(job({ state: 'completed', exit_reason: 'completed' })).label).toBe('Finished')
    expect(agentStatus(job({ state: 'completed', exit_reason: 'max_rounds' })).label).toBe(
      'Finished at step limit'
    )
    expect(agentStatus(job({ state: 'failed', exit_reason: 'error' })).label).toBe('Failed')
    expect(agentStatus(job({ state: 'failed', exit_reason: 'stalled' })).label).toBe('Stalled')
    expect(agentStatus(job({ state: 'interrupted', exit_reason: 'stopped' })).label).toBe('Stopped')
    // Known-to-be-gone is not "still working": the stuck-card bug elsewhere.
    expect(agentStatus(null)).toMatchObject({ label: 'Lost when Marvi restarted', live: false })
    expect(agentStatus(undefined, 'Handing over')).toMatchObject({ label: 'Handing over', live: true })
  })

  it('counts time the way it is read', () => {
    expect(elapsed(12.4)).toBe('12s')
    expect(elapsed(64)).toBe('1m 04s')
  })
})

describe('job card', () => {
  it('shows the face, name, role, state and what it is doing', () => {
    const html = renderToStaticMarkup(<AgentJobCard job={job()} roster={feed.agents} />)
    expect(html).toContain('Jarvi')
    expect(html).toContain('Computer use')
    expect(html).toContain('Working')
    expect(html).toContain('Reading the window')
    expect(html).toContain('role="img"')
  })

  it('says what a waiting agent wants to do', () => {
    const html = renderToStaticMarkup(
      <AgentJobCard job={job({ state: 'awaiting_approval', action: 'computer_action close' })} />
    )
    expect(html).toContain('Needs your approval')
    expect(html).toContain('Wants to run computer_action close')
  })

  it('reports a finished job by its summary and a vanished one as lost', () => {
    const done = renderToStaticMarkup(
      <AgentJobCard
        job={job({ state: 'completed', exit_reason: 'completed', summary: 'Closed it.' })}
      />
    )
    expect(done).toContain('Finished')
    expect(done).toContain('Closed it.')
    const lost = renderToStaticMarkup(<AgentJobCard fallbackName="Nova" job={null} />)
    expect(lost).toContain('Lost when Marvi restarted')
    expect(lost).toContain('Nova')
  })
})

describe('transcript', () => {
  it('shows the task, the list and each step with its outcome', () => {
    const detail: AgentJobDetail = {
      ...job(),
      revision: 3,
      todos: [
        { content: 'Open it', status: 'completed' },
        { content: 'Read it', status: 'in_progress' }
      ],
      events: [
        { at: 1, kind: 'said', text: 'Starting.' },
        { at: 2, kind: 'tool', text: 'computer_action action=launch_app', outcome: 'ok' },
        { at: 3, kind: 'tool', text: 'computer_action action=click', outcome: 'failed' }
      ]
    }
    const html = renderToStaticMarkup(<TranscriptView detail={detail} />)
    expect(html).toContain('Open Notepad and read its title')
    expect(html).toContain('[x]')
    expect(html).toContain('[&gt;]')
    expect(html).toContain('Starting.')
    expect(html).toContain('agent-event is-tool is-failed')
    expect(renderToStaticMarkup(<TranscriptView detail={null} />)).toContain('Marvi restarted')
  })
})

describe('status-bar roster', () => {
  it('lists every agent and who is working now', () => {
    const html = renderToStaticMarkup(<AgentsPanel feed={feed} />)
    for (const name of ['Harvi', 'Jarvi', 'Worker']) expect(html).toContain(name)
    expect(html).toContain('WORKING NOW')
    expect(html).toContain('Reading the window')
  })

  it('says so when nobody is working, and when the Gateway is not there', () => {
    expect(renderToStaticMarkup(<AgentsPanel feed={{ ...feed, jobs: [] }} />)).toContain(
      'Nobody is working.'
    )
    expect(renderToStaticMarkup(<AgentsPanel feed={null} />)).toContain('not reachable')
  })
})

describe('delegate receipt', () => {
  it('reads the job from the enveloped text a chat tool row stores', () => {
    const stored =
      '[EXTERNAL DATA tool:delegate nonce=1]\n{"ok": true, "id": "3a6e2bf8", "agent": "jarvi", "name": "Jarvi"}\n[END EXTERNAL DATA nonce=1]'
    expect(receiptOf(stored)).toMatchObject({ id: '3a6e2bf8', name: 'Jarvi', agent: 'jarvi' })
    expect(receiptOf({ ok: false, detail: 'busy' })).toMatchObject({ ok: false })
    expect(receiptOf(undefined)).toEqual({})
  })

  it('keeps the agent card out of the folded work log', () => {
    expect(groupWork({ type: 'tool-call', toolName: 'delegate' } as never)).toBeNull()
    expect(groupWork({ type: 'tool-call', toolName: 'web_search' } as never)).not.toBeNull()
  })
})
