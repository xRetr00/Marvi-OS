// Throwaway visual probe for the sub-agent UI. Not shipped; deleted after use.
import '../src/renderer/src/assets/base.css'
import '../src/renderer/src/assets/main.css'
import { createRoot } from 'react-dom/client'
import { AgentJobCard, AgentsPanel, DelegateCard } from '../src/renderer/src/components/agents/agents'
import type { AgentJob, AgentsFeed } from '../src/shared/agents'

const now = Date.now() / 1000
const job = (o: Partial<AgentJob>): AgentJob => ({
  id: 'aa11bb22', agent: 'jarvi', name: 'Jarvi', mode: '', task: 'Open Notepad, read the title, close it',
  state: 'running', exit_reason: '', summary: '', progress: 'Reading the window title', seconds: 14,
  started_at: now - 14, finished_at: null, tokens: 12000, detail: '', ...o
})
const feed: AgentsFeed = {
  revision: 3,
  agents: [
    { key: 'harvi', name: 'Harvi', description: "Marvi's native coding sub-agent. Reads, changes and tests code under the workspace root.", when_to_use: 'Any coding job.', named_per_job: false },
    { key: 'jarvi', name: 'Jarvi', description: "Marvi's computer-use sub-agent. Operates Windows applications through the Cua driver.", when_to_use: 'Anything done in a desktop application.', named_per_job: false },
    { key: 'talos', name: 'Talos', description: "Marvi's browser-use sub-agent.", when_to_use: 'Anything with a URL that takes more than one step.', named_per_job: false },
    { key: 'worker', name: 'Worker', description: 'Generic sub-agent for a long job.', when_to_use: 'Research across sources.', named_per_job: true }
  ],
  jobs: [
    job({}),
    job({ id: 'cc33dd44', agent: 'worker', name: 'Nova', task: 'Compare three laptops', progress: 'Reading reviews' }),
    job({ id: 'ee55ff66', agent: 'harvi', name: 'Harvi', state: 'completed', exit_reason: 'completed', summary: 'add() returned a - b; changed to a + b and pytest reports 1 passed.', finished_at: now - 60, started_at: now - 68 })
  ]
}
const detail = { ...feed.jobs[0], revision: 3, todos: [{ content: 'Open Notepad', status: 'completed' }, { content: 'Read the title', status: 'in_progress' }, { content: 'Close it', status: 'pending' }], events: [
  { at: now - 12, kind: 'said', text: 'Launching Notepad first.' },
  { at: now - 11, kind: 'tool', text: 'computer_action action=launch_app, arguments=<1 items>', outcome: 'ok' },
  { at: now - 6, kind: 'tool', text: 'computer_action action=get_window_state', outcome: 'running' }
] }
// @ts-expect-error probe mock
window.marvi = {
  getAgents: async (after?: number) => { if (after !== undefined) await new Promise((r) => setTimeout(r, 25000)); return feed },
  getAgentJob: async () => detail,
  stopAgentJob: async () => ({ ok: true })
}
const receipt = '[EXTERNAL DATA tool:delegate]\n{"ok": true, "id": "aa11bb22", "agent": "jarvi", "name": "Jarvi"}\n[END EXTERNAL DATA]'
createRoot(document.getElementById('root')!).render(
  <div style={{ display: 'flex', gap: 32, padding: 24, alignItems: 'flex-start', color: 'var(--ui-text-primary)' }}>
    <div className="agents-panel" style={{ position: 'static' }}><AgentsPanel feed={feed} /></div>
    <div style={{ width: 420 }}>
      <p style={{ color: '#888', font: '11px monospace' }}>CHAT — delegate card (live)</p>
      <DelegateCard args={{ agent: 'jarvi', task: 'Open Notepad' }} result={receipt} running={false} />
      <p style={{ color: '#888', font: '11px monospace' }}>CHAT — handing over / approval / failed / lost</p>
      <DelegateCard args={{ agent: 'talos', task: 'Book the table for two' }} result={undefined} running={true} />
      <AgentJobCard job={job({ id: 'x1', agent: 'talos', name: 'Talos', state: 'awaiting_approval', action: 'browser_action submit {"form":"booking"}' })} roster={feed.agents} />
      <AgentJobCard job={job({ id: 'x2', agent: 'harvi', name: 'Harvi', state: 'failed', exit_reason: 'stalled', summary: 'it made no progress for 450 seconds, so it was stopped', finished_at: now })} roster={feed.agents} />
      <AgentJobCard job={null} fallbackName="Rune" fallbackAgent="worker" roster={feed.agents} />
      <p style={{ color: '#888', font: '11px monospace' }}>EXPANDED — live transcript</p>
      <AgentJobCard defaultOpen job={feed.jobs[0]} roster={feed.agents} />
    </div>
  </div>
)
