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
  id: string
  toolkit: string
  status: string
  connected: boolean
  needsReconnect: boolean
  alias: string
  scope: 'read' | 'write' | 'admin'
  syncEnabled: boolean
}

export interface AccountToolkit {
  slug: string
  name: string
  description: string
  logo: string
  nativeMemory: boolean
}

export interface AccountSyncState {
  toolkit: string
  connectionId: string
  cursor: string
  status: string
  lastAttemptAt: string | null
  lastSuccessAt: string | null
  lastError: string
  itemsSeen: number
  lastCount: number
}

export interface AccountPage {
  available: boolean
  detail: string
  accounts: ConnectedAccount[]
  sync: {
    providers: Array<{ toolkit: string; label: string }>
    connections: AccountSyncState[]
  }
  triggers: {
    connected: boolean
    received: number
    lastEventAt: string | null
    lastError: string
    transport: string
  }
}

/**
 * The Capabilities > Connectors surface, backed by the Gateway's `/connectors`
 * contract. Deliberately smaller than `AccountPage`/`ConnectedAccount`: this is
 * the openhuman-style card grid, not the older row-based Accounts settings
 * page, and it never grew the sync/triggers machinery because that stays on
 * Composio's side of the Gateway now.
 */
export type ConnectorStatus =
  | 'connected'
  /** Composio is still setting the connection up. Not the same as expired,
   * and reading it as expired told the user their new connector was broken. */
  | 'connecting'
  | 'expired'
  | 'disconnected'
  | 'preview'

export interface ConnectorRow {
  slug: string
  name: string
  status: ConnectorStatus
  connectionId: string
  scope: 'read' | 'write' | 'admin'
  connections: number
  error: string
}

export interface ConnectorsPage {
  available: boolean
  connectors: ConnectorRow[]
}

/** An installed MCP server, from `GET /mcp/servers`. */
export interface McpInstalledServer {
  id: string
  name: string
  status: string
  tools: number
  source: 'installed'
}

/** One registry search hit, from `GET /mcp/registry`. Not yet installed. */
export interface McpRegistryServer {
  qualifiedName: string
  name: string
  description: string
  author: string
  source: 'registry'
}

export interface McpServersPage {
  servers: McpInstalledServer[]
}

export interface McpRegistryPage {
  servers: McpRegistryServer[]
  totalPages: number
}

export type MaintenanceAction = 'doctor' | 'setup' | 'models' | 'diagnostics'

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
  summary: {
    total?: number
    facts?: string[]
    recent_events?: string[]
    graph?: { entities: number; relations: number }
  }
}

/**
 * What is in the files somebody picked, before anything is written.
 *
 * Shown first because the failure mode of choosing the wrong file is silence
 * rather than an error: a config file reads as empty and the import reports
 * success.
 */
export interface MemoryImportPreview {
  files: Array<{ name: string; found: number }>
  found: number
  /** Lines the credential gate will not import, with what matched. Shown
   * before the import rather than after: somebody bringing in years of another
   * assistant's notes should be told that thirteen of them were passwords
   * while they can still change their mind. */
  refused: Array<{ reason: string; quote: string }>
  sample: string[]
}

/** Files, or a provider to read over the network. */
export interface MemoryImportRequest {
  paths?: string[]
  provider?: 'honcho' | 'mem0'
  /** The Honcho workspace, or the Mem0 user. */
  scope?: string
}

export interface MemoryImportSources {
  /** What to paste into ChatGPT, Claude, Gemini or Grok. Served by the Gateway
   * so the format it asks for and the parser that reads it stay together. */
  packPrompt: string
  packFormat: string
  provider: string
  /** Whether a key for each API source can be found at all. */
  honcho: boolean
  mem0: boolean
}

export interface MemoryImportResult {
  found: number
  imported: number
  refused?: Array<{ reason: string; quote: string }>
  detail: string
  source?: string
  /** The dream run over what arrived, when anything did. */
  dreamt?: { considered: number; concluded: number; linked: number; retired: number }
}

export type MemoryGraphMode = 'tree' | 'contacts'

export interface MemoryGraphNode {
  id: string
  kind: 'root' | 'source' | 'summary' | 'chunk' | 'contact'
  label: string
  level?: number
  memory_kind?: string
  entity_kind?: string
  trusted?: boolean
  provenance?: string
  at?: string
}

export interface MemoryGraphEdge {
  id: string
  source: string
  target: string
  label?: string
  trusted?: boolean
  provenance?: string
}

export interface MemoryGraphPage {
  mode: MemoryGraphMode
  nodes: MemoryGraphNode[]
  edges: MemoryGraphEdge[]
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

export type UpdateChannel = 'release' | 'nightly'

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
  commits: UpdateCommit[]
  error?: string | null
}

export interface UpdateCommit {
  sha: string
  summary: string
  author: string
  /** Unix timestamp in seconds, supplied by git. */
  at: number
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
  /** A question Marvi asked, with the options she offered. */
  question: PendingQuestion | null
  /** A credential Marvi asked for, as a masked field. */
  secret: PendingSecret | null
}

/**
 * A credential Marvi asked for.
 *
 * Its own channel rather than a kind of question, for one reason that matters:
 * a question's answer goes into the conversation, and this one must never.
 * What the user types goes desktop → Gateway → settings store and stops there;
 * Marvi is told the name and that it was saved.
 */
export interface PendingSecret {
  id: string
  /** The setting it will be saved as, e.g. `OPENROUTER_API_KEY`. */
  name: string
  /** Why she is asking. Somebody about to type a credential is owed a reason. */
  why: string
}

/**
 * Something Marvi asked, drawn as options rather than said as prose.
 *
 * Nothing is waiting on it. The card is a shortcut for saying the answer out
 * loud: pressing an option sends those words into the conversation as the
 * user's turn, which is what would have happened anyway. That is why there is
 * no token here and no way to decline — a question can simply be answered by
 * saying something else.
 */
export interface PendingQuestion {
  id: string
  text: string
  /** In order, best first. The first carries the recommendation label. */
  choices: string[]
  multiSelect: boolean
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

export interface UsageCounters {
  input: number
  output: number
  cachedInput: number
  reasoning: number
  billable: number
}

export interface UsageAccount {
  state: 'ready' | 'error'
  scope?: string
  currency?: string
  spent?: number | null
  periodSpent?: number | null
  remaining?: number | null
  limit?: number | null
  balances?: Array<{ currency: string; remaining: string }>
  detail?: string
}

export interface UsageProvider {
  name: string
  label: string
  accessPath: 'api' | 'plan' | 'local'
  configured: boolean
  usage: UsageCounters
  account: UsageAccount | null
  accountCollection: string
}

export interface UsageDay extends UsageCounters {
  date: string
}

export interface UsageHour extends UsageCounters {
  hour: string
}

export interface UsagePage {
  totals: UsageCounters
  providers: UsageProvider[]
  daily: UsageDay[]
  hourly: UsageHour[]
  account: Record<string, UsageAccount>
  updatedAt: string | null
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
  voice?: VoiceVerdict
}

/**
 * What the chosen model means for the spoken conversation.
 *
 * Voice is where a model's thinking is a thing you sit and wait through, and
 * it is chosen on a page that said nothing about that.
 */
export interface VoiceVerdict {
  model: string
  reasons: boolean
  /** Observed from a refusal, not advertised: no catalog states it. */
  reasoningLockedOn: boolean
  effort: string
  /** Empty when there is nothing to say. */
  warning: string
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
  /** True for a voice learned from a recording rather than shipped. */
  cloned?: boolean
}

export interface TTSEngine {
  id: string
  name: string
  description: string
  runtime: string
  defaultVoice: string
  /** Whether this engine speaks in a voice recorded for it. */
  cloning: boolean
  available: boolean
}

export interface VoicePage {
  engineSetting: string
  selectedEngine: string
  engineMissing: boolean
  /** The environment variable a choice is written to. */
  setting: string
  selected: string
  /** True when a voice was chosen and its file is no longer there — said
   * rather than silently corrected. */
  missing: boolean
  engines: TTSEngine[]
  voices: InstalledVoice[]
}

/** A voice Marvi learned from a recording. */
export interface VoiceClone {
  id: string
  name: string
  engine: string
  seconds: number
}

export interface VoiceClonePage {
  /** The engines that can speak in a recorded voice. Two of the three. */
  engines: string[]
  shortestSeconds: number
  longestSeconds: number
  clones: VoiceClone[]
}

/** One local recogniser Marvi can listen with. */
export interface STTEngine {
  id: string
  name: string
  description: string
  runtime: string
  available: boolean
  /** What the bakeoff measured, so the picker can show the trade rather than
   * asking somebody to remember which of two names was the accurate one. */
  measured: {
    wer?: number
    rtf?: number
    first_partial_ms_p50?: number
    arabic_wer?: number
    corpus?: string
  }
}

export interface RecogniserPage {
  /** The environment variable a choice is written to. */
  setting: string
  selected: string
  /** True when a recogniser was chosen and is no longer installed. */
  missing: boolean
  engines: STTEngine[]
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
  heardSecondsAgo: number | null
  recentlyHeard: boolean
  confidence: number
  setting: string
  thresholdSetting: string
  /**
   * Which microphone the standalone listener opens. Empty means the system
   * default, which is what it always used - and on a machine with a webcam, a
   * headset and a speakerphone that is frequently the wrong one.
   *
   * Enumerated by the listener's own audio stack rather than the browser's:
   * PortAudio and Chromium see different devices under different names, and a
   * picker built from the wrong list offers microphones the thing doing the
   * listening cannot open.
   */
  device: string
  deviceSetting: string
  devices: { name: string; label: string; default: boolean }[]
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
    /**
     * Seconds since the listener last said anything, or null when it has
     * never run.
     *
     * "Registered but not running" was reported as one state and it is two. A
     * listener registered a second ago has not started yet; one silent for
     * thirty hours has died — and the status bar said STARTING for both.
     */
    silentFor: number | null
    everRan: boolean
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
  thread_id?: string
  parent_id?: number | null
  branch_id?: string
  parts?: ChatPart[]
  attachments?: ChatAttachment[]
}

export type ChatPart =
  | { type: 'text'; text: string }
  | { type: 'source'; title: string; url: string }
  | { type: 'attachment'; attachment_id: string; name: string; media_type: string; size: number }
  | { type: 'image'; attachment_id?: string; url?: string; alt?: string }
  | { type: 'file'; attachment_id?: string; name: string; media_type?: string; size?: number }
  | { type: 'tool'; name: string; status?: string; content?: string }
  | ChatWidgetPart

export interface ChatWidgetPart {
  type: 'widget'
  id: string
  version: 1
  kind:
    | 'sources'
    | 'metrics'
    | 'comparison'
    | 'table'
    | 'timeline'
    | 'weather'
    | 'gallery'
    | 'document'
    | 'status'
  title: string
  status: 'complete' | 'loading' | 'error'
  data: Record<string, unknown>
}

export interface ChatContext {
  input_tokens: number
  cached_tokens: number
  context_window: number
  reply_reserve: number
  messages: number
  files: number
  sources: number
  provider: string
  model: string
}

export interface ChatAttachment {
  id: string
  thread_id: string
  message_id: number | null
  name: string
  media_type: string
  size: number
  created_at: string
  kind: 'image' | 'document'
}

export interface ChatThread {
  id: string
  title: string
  created_at: string
  updated_at: string
  archived: boolean
  active_message_id: number | null
  active_branch: string
  selected_provider: string
  selected_model: string
  selected_effort: string
  message_count: number
}

export interface ChatPage {
  messages: ChatEntry[]
  available: boolean
  threads: ChatThread[]
  active_thread: string
  context: ChatContext
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

/**
 * What a skill's use says about it.
 *
 * Nothing knew which skills had ever been read, so "which of these is worth
 * keeping?" had no answer and the catalogue could only grow — and every skill
 * in it costs a line in the prompt on every turn.
 */
export interface SkillUsage {
  uses: number
  lastUsed: string
  /** Marvi wrote it herself, which is what makes it eligible for the sweep. */
  mine: boolean
  pinned: boolean
  state: 'active' | 'stale' | 'archived'
}

/** One installed skill, with what is known about its use. */
export interface InstalledSkill {
  name: string
  description: string
  source: string
  /** Empty means every platform. */
  platforms: string[]
  /** Settings it needs before it is any use here. */
  requires: string[]
  /** False when it is for another platform, or needs something not configured.
   * It stays listed here and is kept out of the prompt. */
  applies: boolean
  usage: SkillUsage
}

export interface SkillsPage {
  skills: InstalledSkill[]
  archived: string[]
  trustedSources: string[]
  trustedSetting: string
}

/** What reading a skill's text turned up before Marvi is given it. */
export interface SkillScan {
  tier: 'bundled' | 'trusted' | 'community'
  blocked: boolean
  reason: string
  findings: Array<{ severity: 'danger' | 'caution'; rule: string; why: string; quote: string }>
}

export interface SkillReview {
  ok: boolean
  staged?: string
  skill: { name: string; description: string; requested_tools: string[] }
  instructions: string
  warnings: string[]
  tools?: { tools: string[]; unknown: string[]; still_sensitive: string[] }
  scan?: SkillScan
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
  roomEvent: null,
  question: null,
  secret: null
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
  /**
   * False when the plugin is on disk but not live in the running Gateway: an
   * import that failed, or an update applied after startup. Installed and
   * doing nothing looked identical to installed and working.
   */
  running: boolean
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
  mode: 'action' | 'agent'
  /** A self-contained job brief. Empty for fixed Gateway actions. */
  prompt: string
  /** Empty provider/model/effort means use Marvi's automatic auxiliary route. */
  provider: string
  model: string
  effort: string
  /** Exact Gateway tools this job may see. Empty means the full current catalogue. */
  tool_names: string[]
  /** Messaging destination id. `local` retains output only. */
  delivery: string
  repeat_count: number | null
  completed_runs: number
  next_run: string | null
  last_run: string | null
  last_error: string | null
  last_output: string | null
  last_provider: string | null
  last_model: string | null
  last_tokens: number
  last_delivery: string | null
}

export interface SchedulePage {
  schedules: ScheduleRow[]
  actions: Record<string, string>
  running: boolean
  tools: string[]
  delivery_targets: { id: string; name: string; available: boolean }[]
  efforts: string[]
}

export interface NewSchedule {
  name: string
  when: string
  message?: string
  action?: string
  insist?: boolean
  mode?: 'action' | 'agent'
  prompt?: string
  provider?: string
  model?: string
  effort?: string
  tool_names?: string[]
  delivery?: string
  repeat_count?: number | null
}

/**
 * Which model does which job.
 *
 * Marvi picks one model for the hardest thing she does and then uses it for
 * everything, including work that needs none of it. A role may name its own
 * provider and model; unset means the main one, which is what happened before
 * and remains a good answer.
 */
export interface AuxiliaryRole {
  key: string
  title: string
  why: string
  /** What choosing well buys. Empty when the honest answer is "not much". */
  gain: string
  setting: string
  provider: string
  model: string
  /** How hard the chosen model should think. Empty means the model's own
   * default, and it is cleared whenever the role goes back to auto. */
  effort: string
  effortSetting: string
  auto: boolean
}

export interface AuxiliaryPage {
  roles: AuxiliaryRole[]
  separator: string
  providers: { name: string; label: string }[]
  /** The main provider, so the page can name jobs pinned away from it. */
  main: string
}

/**
 * How far the file tools may reach, and what is refused to all of them.
 *
 * Three settings rather than one, because the honest answer is usually
 * asymmetric: read the whole disk, write only where I said. The blacklist
 * holds over both, including `general` — which is the only reason `general`
 * is on offer at all.
 */
export interface WorkspacePolicy {
  root: string
  rootExists: boolean
  readScope: 'strict' | 'general'
  writeScope: 'strict' | 'general'
  /** What Marvi may do with a file that holds credentials. */
  secretAccess: 'off' | 'masked' | 'full'
  /** What the user added. The built-in rules are separate and always apply. */
  blacklist: string[]
  /** Refusals that hold whatever the settings say, and cannot be removed. */
  builtin: { pattern: string; why: string; reading: boolean; secret: boolean }[]
  tools: { read: string[]; write: string[] }
}

/**
 * Which language Marvi listens in, and which she answers in.
 *
 * Two questions, not one: for a bilingual household the point is to speak one
 * language at her and get another back. `enforceable` is the honest part —
 * only English has a recogniser that cannot produce anything else, so every
 * other choice is a preference the multilingual model may ignore.
 */
export interface LanguagePolicy {
  understand: string
  understandOptions: { code: string; name: string; locked: boolean }[]
  speak: string
  speakOptions: { code: string; name: string }[]
  /** False when the choice is a preference rather than a lock. */
  enforceable: boolean
  /** Whether the English-only recogniser is actually on disk. */
  englishModelInstalled: boolean
}

export interface LanguageUpdate {
  understand?: string
  speak?: string
}

/**
 * Where embeddings come from, when memory starts using them.
 *
 * `off` is the default and keyword recall still works — a memory system that
 * silently started calling an API would be a surprise nobody asked for.
 */
export interface MemoryPolicy {
  provider: 'local' | 'honcho' | 'mem0'
  providers: string[]
  providerUrl: string
  /** Whether a memory-provider key is stored. Never the key. */
  providerKeySet: boolean
  userId: string
  workspace: string
  source: 'off' | 'local' | 'provider'
  sources: string[]
  model: string
  url: string
  /** Whether a key is stored. Never the key. */
  keySet: boolean
  defaultLocalModel: string
  defaultProviderModel: string
  /** The auxiliary role that decides what to keep from a turn. */
  role: string
  roleConfigured: boolean
  /**
   * Whether a model reads the memories and answers, or the search results
   * reach the caller as they are.
   *
   * On by default. It is paid inside the window the voice path already spends
   * waiting for the user to stop speaking, and it is the only part of memory
   * that can say "I do not know" — a search returns its five nearest rows
   * whatever it was asked.
   */
  reader: boolean
}

/**
 * A skill the last turn suggested writing down, waiting for a person.
 *
 * Almost always absent. It appears when the user corrected *how* Marvi works
 * — "stop formatting like that" — which is the correction that used to be
 * forgotten by the next session, because memory holds facts and the prompt is
 * fixed.
 */
export interface SkillProposal {
  /** `create` for a new skill, `patch` to replace one that exists. */
  act: 'create' | 'patch'
  name: string
  description: string
  /** The whole SKILL.md body, shown before anything is written. */
  body: string
  /** One sentence on what in the conversation prompted it. */
  why: string
}

export interface MemorySettingsUpdate {
  provider?: string
  provider_url?: string
  provider_key?: string
  user_id?: string
  workspace?: string
  source?: string
  model?: string
  url?: string
  key?: string
  reader?: boolean
}

export interface WorkspaceUpdate {
  root?: string
  read_scope?: string
  write_scope?: string
  blacklist?: string[]
  secret_access?: string
}

/**
 * Who the camera knows, and who is waiting to be named.
 *
 * A pending sighting carries the crop that produced it, because "one unknown
 * visitor" is not something anybody can act on and a face is.
 */
export interface FaceLibrary {
  ok: boolean
  detail?: string
  owner: string
  people: { name: string; owner: boolean; samples: number; at?: string }[]
  pending: {
    id: number
    at?: string
    score?: number
    image: string
    /** Who the face is closest to, whatever the score. */
    nearest?: { name?: string; score?: number }
  }[]
}

/** A bounded, compressed frame produced by the Smart Room sidecar on demand. */
export interface RoomVisionPreview {
  available: boolean
  captured_at?: string
  error?: string
  image?: string
  vision?: Record<string, unknown>
}
