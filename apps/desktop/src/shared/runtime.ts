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

/** Which model each part of the voice path is using, by name. The status bar
 * says whether things are up; this says which ones. */
export interface ModelSummary {
  llm: string
  stt: string
  tts: string
}

export interface AssistantState {
  phase: AssistantPhase
  caption: string
  detail: string | null
  level: number
  yolo: boolean
  /** The last utterance each way, for the live transcript. Only the latest:
   * a glance while talking, not a record. */
  heard: string
  spoken: string
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
  env: { key: string; model: string; url: string; effort: string }
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
  /** Local providers only: is something listening right now? null = not probed. */
  reachable: boolean | null
}

export interface ProviderPage {
  providers: ProviderRow[]
  selected: string | null
  /** Saved settings with credentials masked; never the real values. */
  settings: Record<string, string>
  totals: { input: number; output: number; cachedInput: number; billable: number }
}

/** One model a provider says it has, as `GET /models` reports it. */
export interface ModelCard {
  id: string
  name: string
  provider: string
  context: number
  /**
   * Empty when the model cannot reason. Per model rather than per provider
   * because a gateway fronts both kinds under one credential, so the effort
   * control is hidden rather than offered where it would be ignored.
   */
  efforts: string[]
  reasons: boolean
  promptPerMillion: number | null
  completionPerMillion: number | null
  vision: boolean
}

export interface ModelProvider {
  provider: string
  label: string
  /** The provider's configured default — what a turn gets without an override. */
  selected: string
  routesUpstream: boolean
  /** False when the provider is configured but listed nothing, which is worth
   * saying out loud rather than showing as an empty dropdown. */
  reachable: boolean
  models: ModelCard[]
}

export interface ModelPage {
  providers: ModelProvider[]
}

/** One upstream that can serve an OpenRouter model, and on what terms. */
export interface Upstream {
  slug: string
  name: string
  context: number
  quantization: string
  promptPerMillion: number | null
  completionPerMillion: number | null
  /** Often null: OpenRouter publishes it per endpoint and leaves most unset,
   * so the UI says "unknown" rather than pretending it is zero. */
  latencyMs: number | null
  throughput: number | null
  uptime: number | null
}

export interface UpstreamPage {
  model: string
  route: Record<string, Record<string, unknown>>
  policies: string[]
  upstreams: Upstream[]
}

/** One installed TTS voice. `id` is exactly what the setting takes. */
export interface InstalledVoice {
  id: string
  name: string
  language: string
  gender: string
}

export interface VoicePage {
  /** The environment variable a choice is written to. */
  setting: string
  selected: string
  /** True when a voice was chosen and its file is no longer there — said
   * rather than silently corrected. */
  missing: boolean
  voices: InstalledVoice[]
}

/** What the wake word is doing. */
export interface WakeStatus {
  enabled: boolean
  model: string
  modelPresent: boolean
  /** Switched on *and* the model is there. A missing model leaves Marvi
   * answering every turn rather than deaf, so those differ. */
  armed: boolean
  threshold: number
  window: number
  heardSecondsAgo: number | null
  recentlyHeard: boolean
  confidence: number
  setting: string
  thresholdSetting: string
  /**
   * The standalone listener that runs at login, which is the only part of the
   * wake word that can hear you before Marvi is open.
   *
   * `autostart` and `running` are separately reported on purpose: registered
   * but not running is the failure that matters, and folding them into one
   * boolean makes a listener that crashed look like one nobody has spoken to.
   */
  listener: {
    autostart: boolean
    running: boolean
    error: string
  }
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

export interface SetupComponent {
  name: string
  kind: string
  title: string
  why: string
  needed_for: string[]
  bytes_total: number
  installed: boolean
  detail: string
  /** Live download position while an install is running, else absent. The
   * install request blocks for the whole download, so polling this is the only
   * way the page can show anything during it. */
  progress?: { file: string; bytes_done: number; bytes_total: number } | null
}

export interface SetupPage {
  components: SetupComponent[]
  plan: { install: Array<{ name: string; title: string; bytes: number }>; bytes_total: number }
  install_root: string
  disk_ok: boolean
  disk_detail: string
}

export interface HardwareAnswer {
  ask: boolean
  use_gpu: boolean
  reason: string
  prompt?: string
  hardware: { gpus: Array<{ name: string; memory_mb: number; usable: boolean }> }
}

export interface StoreSkill {
  name: string
  description: string
  source: string
  repo: string
  path: string
  installed: boolean
}

export interface SkillReview {
  ok: boolean
  staged?: string
  skill: { name: string; description: string; requested_tools: string[] }
  instructions: string
  warnings: string[]
  tools?: { tools: string[]; unknown: string[]; still_sensitive: string[] }
}

export interface McpServerRow {
  name: string
  command: string
  enabled: boolean
  on_path: boolean
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
  model: ModelSummary
}

export const DEFAULT_ASSISTANT_STATE: AssistantState = {
  phase: 'ready',
  caption: 'Say Marvi',
  detail: null,
  level: 0,
  yolo: false,
  heard: '',
  spoken: '',
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
  // Not DEFAULT_ASSISTANT_STATE: that one is the *ready* state, and reusing it
  // here made an unreachable Marvi say "Say Marvi" and report VOICE READY in
  // the status bar. An assistant we cannot reach is in its error phase.
  model: { llm: '', stt: '', tts: '' },
  assistant: {
    ...DEFAULT_ASSISTANT_STATE,
    phase: 'error',
    caption: 'Gateway unavailable',
    detail: 'Marvi is not answering'
  }
}

/** What the microphone and camera rows should say, and never more than is known.
 *
 * `AssistantState` used to carry `microphone: true` and `camera: true`. Nothing
 * ever assigned them, so the app reported "MIC ON / CAM ON" and "CAMERA: ALWAYS
 * ON" with the Gateway offline and vision disabled. A device indicator that is
 * always on is worse than no indicator: it is the one place a user looks to
 * check whether they are being listened to.
 *
 * The components that own the devices are the only honest source: the voice
 * session publishes the microphone, the Smart Room sidecar publishes its
 * camera state through the Gateway runtime component.
 */
export type DeviceState = 'on' | 'off' | 'unknown'

export function deviceState(
  runtime: Pick<RuntimeStatus, 'state' | 'components'>,
  device: 'microphone' | 'camera'
): DeviceState {
  // Nothing is known about a machine we cannot reach.
  if (runtime.state === 'offline') return 'unknown'
  const component = runtime.components[device === 'microphone' ? 'voice' : 'vision']
  if (!component) return 'unknown'
  if (component.state === 'ready') return 'on'
  if (component.state === 'starting') return 'unknown'
  return 'off'
}

export function deviceLabel(state: DeviceState): string {
  return state === 'on' ? 'ON' : state === 'off' ? 'OFF' : '?'
}

/** A desktop plugin: a backend Marvi installs from a repository and runs. */
export interface PluginRow {
  name: string
  title: string
  why: string
  repo: string
  ref: string
  installed: boolean
  version: string
  commit: string
  tools: string[]
  detail: string
  /** False when the plugin declares platforms this machine is not one of. */
  supported: boolean
}

export interface PluginPage {
  plugins: PluginRow[]
  install_root: string
  data_root: string
}

/** A reminder or scheduled check the user set. */
export interface ScheduleRow {
  id: number
  name: string
  action: string
  kind: string
  expression: string
  message: string
  enabled: boolean
  created_at: string
  /** Speak even during quiet hours and while the room is asleep. Opt-in. */
  insist: boolean
  last_run: string | null
  last_error: string | null
}

export interface SchedulePage {
  schedules: ScheduleRow[]
  actions: Record<string, string>
  running: boolean
}
