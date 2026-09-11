import { describe, expect, it } from 'vitest'

import type { AgentJob, AgentsFeed } from '../../../shared/agents'
import { plain } from '../components/agents/agent-state'
import { delegatedJobs, isBackground, nextJobToReport, reportedJobs } from './job-reports'
import type { ChatMessage } from './types'

const message = (overrides: Partial<ChatMessage>): ChatMessage => ({
  id: 1,
  at: '',
  role: 'assistant',
  content: '',
  meta: {},
  threadId: 'default',
  parentId: null,
  branchId: 'main',
  parts: [],
  attachments: [],
  ...overrides
})

const delegated = (id: string, name = 'delegate'): ChatMessage =>
  message({
    parts: [
      {
        type: 'tool',
        name,
        content: `[EXTERNAL DATA tool:${name}]\n{"ok": true, "id": "${id}", "agent": "jarvi"}\n[END EXTERNAL DATA]`
      }
    ]
  })

const feed = (...jobs: Array<Pick<AgentJob, 'id' | 'state'>>): AgentsFeed => ({
  revision: 1,
  agents: [],
  jobs: jobs as AgentJob[]
})

describe('reporting finished work back into Chat', () => {
  it('finds the jobs this thread started, by either delegating tool', () => {
    expect(delegatedJobs([delegated('aa'), delegated('bb', 'delegate_to_coder')])).toEqual([
      'aa',
      'bb'
    ])
  })

  it('reports a job once it has ended, and not while it works', () => {
    const messages = [delegated('aa')]
    expect(
      nextJobToReport(messages, new Set(), feed({ id: 'aa', state: 'running' }))
    ).toBeUndefined()
    expect(
      nextJobToReport(messages, new Set(), feed({ id: 'aa', state: 'awaiting_approval' }))
    ).toBeUndefined()
    expect(nextJobToReport(messages, new Set(), feed({ id: 'aa', state: 'completed' }))).toBe('aa')
    expect(nextJobToReport(messages, new Set(), feed({ id: 'aa', state: 'failed' }))).toBe('aa')
  })

  it('never reports twice: the stored note and this session both count', () => {
    const note = message({ role: 'user', meta: { background: 'job_report', job: 'aa' } })
    const done = feed({ id: 'aa', state: 'completed' })
    expect(isBackground(note)).toBe(true)
    expect(nextJobToReport([delegated('aa'), note], reportedJobs([note]), done)).toBeUndefined()
    expect(nextJobToReport([delegated('aa')], new Set(), done, new Set(['aa']))).toBeUndefined()
  })

  it('leaves a job the feed no longer knows alone', () => {
    expect(nextJobToReport([delegated('aa')], new Set(), feed())).toBeUndefined()
    expect(nextJobToReport([delegated('aa')], new Set(), null)).toBeUndefined()
  })
})

describe('a report on a card', () => {
  it('reads as a line, not as Markdown', () => {
    expect(plain('Done — **What I did:**\n1. **Moved the cursor** to `(500, 400)`')).toBe(
      'Done — What I did: 1. Moved the cursor to (500, 400)'
    )
    expect(plain('## Result\n- closed it')).toBe('Result closed it')
  })
})
