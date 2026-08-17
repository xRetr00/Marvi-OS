export const ASSISTANT_PHASES = [
  'ready',
  'wake',
  'listening',
  'thinking',
  'speaking',
  'action',
  'notification',
  'confirmation',
  'error'
] as const

export type AssistantPhase = (typeof ASSISTANT_PHASES)[number]
export type ComponentState = 'ready' | 'starting' | 'pending' | 'offline' | 'error'

export interface ConfirmationRequest {
  token: string
  action: string
  detail: string
  tool: string
  /** The exact arguments the approval is bound to. Echoed back to the Gateway verbatim. */
  arguments: Record<string, unknown>
}

export interface RoomEvent {
  id: number
  at: string
  type: string
  summary: string
}

export interface ConnectedAccount {
  toolkit: string
  status: string
  connected: boolean
  needsReconnect: boolean
}

export interface MemoryEntry {
  id: number
  kind: string
  subject: string
  body: string
  source: string
  trusted: boolean
  at: string
}

export interface MemoryPage {
  total: number
  entries: MemoryEntry[]
  summary: { total?: number; facts?: string[]; recent_events?: string[] }
}

export interface MindDecision {
  id: number
  at: string
  trigger: string
  surface: string
  rule: string
  detail: string
  provider: string
  latency_ms: number
  cost: number
}

export interface InitiativeStatus {
  paused: boolean
  running: boolean
  pending_events: number
  last_runs: Record<string, string>
  last_errors: Record<string, string>
  settings: Record<string, number>
}

export type UpdateChannel = 'release' | 'dev'

export interface UpdateStatus {
  supported: boolean
  inProgress: boolean
  channel: UpdateChannel
  root: string
}

export interface UpdateCheck {
  channel: UpdateChannel
  available: boolean
  upToDate: boolean
  current?: string
  target?: string
  targetRef?: string
  behindBy: number
  signed?: boolean | null
  error?: string | null
}

export interface UpdateResult {
  status: 'ok' | 'failed' | 'aborted' | 'skipped'
  message: string
  from?: string
  to?: string
  branch?: string
  channel?: string
  finishedAt?: string
}

export interface AuditEvent {
  at: string
  event: string
  tool: string
  arguments: Record<string, unknown>
  mode: 'confirm' | 'yolo'
  detail: string | null
}

export interface AssistantState {
  phase: AssistantPhase
  caption: string
  detail: string | null
  level: number
  yolo: boolean
  microphone: boolean
  camera: boolean
  confirmation: ConfirmationRequest | null
  /** Background room event. Rendered only while idle; never steals focus. */
  roomEvent: RoomEvent | null
}

export interface ProviderRow {
  name: string
  label: string
  accessPath: 'api' | 'plan' | 'local'
  apiMode: string
  authType: string
  configured: boolean
  baseUrl: string
  models: { main: string; aux: string; vision: string }
  /** The environment variables this provider reads. Reported by the registry. */
  env: { key: string; model: string; url: string }
  limits: { style: string; windows: string[][]; readable: boolean; note: string }
  usage: { input: number; output: number; cachedInput: number; billable: number }
  cooldown: { seconds_remaining: number; reason: string } | null
  /** Sign-in state for OAuth providers; null for everything else. */
  oauth: {
    connected: boolean
    state: string
    account?: string
    refreshable?: boolean
    encrypted_at_rest?: boolean
    client_id_env: string
    client_id_set: boolean
  } | null
  /** Present only on subscription plans: the terms warning shown before connecting. */
  warning: string | null
}

export interface ProviderPage {
  providers: ProviderRow[]
  selected: string | null
  /** Saved settings with credentials masked; never the real values. */
  settings: Record<string, string>
  totals: { input: number; output: number; cachedInput: number; billable: number }
}

export interface IdentityStatus {
  soul: string
  user: string
  tokens: number
  budget: number
  truncated: boolean
  directory: string
}

export interface ChatEntry {
  id: number
  at: string
  role: string
  content: string
  meta: Record<string, unknown>
}

export interface ChatReply {
  reply: string
  tools_used: string[]
  pending_confirmation: Record<string, unknown> | null
  tokens: number
  provider: string
  error: string
}

export interface DoctorFinding {
  check: string
  area: string
  status: 'ok' | 'warn' | 'fail'
  detail: string
  remedy: {
    kind: 'automatic' | 'confirm' | 'manual' | 'none'
    action: string
    /** For a manual remedy: exactly where to go. Specificity is the value. */
    how: string
    runnable: boolean
  }
  extra: Record<string, unknown>
}

export interface DoctorReport {
  findings: DoctorFinding[]
  summary: { ok: number; warn: number; fail: number }
  healthy: boolean
}

export interface ServiceReport {
  name: string
  state: 'stopped' | 'starting' | 'running' | 'failed' | 'gave up'
  detail: string
  restarts: number
  /** Last lines of the process's own output — the actual reason it died. */
  output: string[]
}

export interface ComponentStatus {
  state: ComponentState
  detail: string
}

export interface RuntimeStatus {
  product: 'Marvi OS'
  version: string
  state: 'ready' | 'starting' | 'degraded' | 'offline' | 'error'
  components: Record<string, ComponentStatus>
  assistant: AssistantState
}

export const DEFAULT_ASSISTANT_STATE: AssistantState = {
  phase: 'ready',
  caption: 'Say Marvi',
  detail: null,
  level: 0,
  yolo: false,
  microphone: true,
  camera: true,
  confirmation: null,
  roomEvent: null
}

export const OFFLINE_RUNTIME: RuntimeStatus = {
  product: 'Marvi OS',
  version: 'unknown',
  state: 'offline',
  components: {
    gateway: { state: 'offline', detail: 'Marvi Gateway unavailable' },
    livekit: { state: 'offline', detail: 'Gateway unavailable' },
    voice: { state: 'offline', detail: 'Gateway unavailable' },
    vision: { state: 'offline', detail: 'Gateway unavailable' },
    accounts: { state: 'offline', detail: 'Gateway unavailable' },
    room: { state: 'offline', detail: 'Gateway unavailable' }
  },
  assistant: DEFAULT_ASSISTANT_STATE
}
