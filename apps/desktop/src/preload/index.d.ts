import type {
  FaceLibrary,
  RoomVisionPreview,
  AuxiliaryPage,
  AssistantState,
  AuditEvent,
  ChatAttachment,
  ChatPage,
  ChatReply,
  ChatThread,
  AccountPage,
  AccountToolkit,
  DoctorReport,
  HardwareAnswer,
  IdentityStatus,
  InitiativeStatus,
  McpServerRow,
  MemoryGraphMode,
  MemoryGraphPage,
  MemoryPage,
  MindDecision,
  ModelPage,
  PluginPage,
  ProviderPage,
  UsagePage,
  RoomEvent,
  RuntimeStatus,
  SchedulePage,
  ServiceReport,
  SetupPage,
  SkillReview,
  StoreSkill,
  UpdateChannel,
  UpdateCheck,
  UpdateResult,
  UpdateStatus,
  UpstreamPage,
  VoicePage,
  WakeStatus,
  WorkspacePolicy,
  WorkspaceUpdate
} from '../shared/runtime'
import type { IslandPlacement } from '../main/island-window'
import type { PetPreferences } from '../main/pet-window'

export interface MarviDesktopApi {
  getVersion: () => Promise<string>
  getBuildInfo: () => Promise<MarviBuildInfo>
  showMain: () => void
  onNavigate: (listener: (page: 'Voice' | 'Activity') => void) => () => void
  getRuntime: () => Promise<RuntimeStatus>
  getVoiceSession: () => Promise<{ url: string; room: string; token: string }>
  setVoiceSessionActive: (active: boolean) => Promise<boolean>
  readAloud: (text: string) => Promise<void>
  stopReadAloud: () => Promise<boolean>
  getDisplays: () => Promise<Array<{ id: number; label: string; primary: boolean }>>
  getIslandPlacement: () => Promise<IslandPlacement>
  setIslandPlacement: (placement: IslandPlacement) => Promise<IslandPlacement>
  getPetPreferences: () => Promise<PetPreferences>
  setPetPreferences: (preferences: PetPreferences) => Promise<PetPreferences>
  onPetLookDirection: (listener: (direction: number | null) => void) => () => void
  onRuntime: (listener: (state: RuntimeStatus) => void) => () => void
  onWakeJoin: (listener: () => void) => () => void
  consumeWakeLaunch: () => Promise<boolean>
  getWakeAutostart: () => Promise<{ autostart: boolean; running: boolean }>
  setWakeAutostart: (
    enabled: boolean,
    device?: string
  ) => Promise<{ autostart: boolean; running: boolean }>
  setYolo: (yolo: boolean) => Promise<RuntimeStatus>
  getAudit: () => Promise<AuditEvent[]>
  getRoomEvents: () => Promise<RoomEvent[]>
  /** Which model does which job. Roles default to the main model. */
  getAuxiliary: () => Promise<AuxiliaryPage | null>
  /** Who the camera knows, and who is waiting to be named. */
  getFaceLibrary: () => Promise<FaceLibrary | null>
  /** A compressed local preview, requested only while Vision is visible. */
  getRoomVisionPreview: () => Promise<RoomVisionPreview | null>
  /** Device reachability and the broker. Lives in `room_health`, not in
   *  `room_state` - reading it from the state showed every device as "not set
   *  up" and the broker as `?:?`, because neither field is there. */
  getRoomHealth: () => Promise<Record<string, unknown> | null>
  /** Press a room control through the Gateway's audited tool router. */
  roomCommand: (
    tool: string,
    args: Record<string, unknown>
  ) => Promise<{ status: string; error?: string; token?: string | null }>
  getInitiative: () => Promise<InitiativeStatus | null>
  setInitiative: (paused: boolean) => Promise<InitiativeStatus | null>
  getDecisions: () => Promise<{ decisions: MindDecision[]; events: unknown[] }>
  getUpdateStatus: () => Promise<UpdateStatus>
  consumeUpdateResult: () => Promise<UpdateResult | null>
  getUpdateChannel: () => Promise<UpdateChannel>
  setUpdateChannel: (channel: UpdateChannel) => Promise<UpdateChannel>
  checkForUpdate: () => Promise<UpdateCheck>
  startUpdate: () => Promise<boolean>
  getMemory: () => Promise<MemoryPage>
  getMemoryGraph: (mode: MemoryGraphMode) => Promise<MemoryGraphPage>
  clearMemory: () => Promise<boolean>
  getAccounts: () => Promise<AccountPage>
  getAccountCatalog: () => Promise<AccountToolkit[]>
  configureAccounts: (apiKey: string) => Promise<{ ok: boolean; detail: string }>
  connectAccount: (toolkit: string) => Promise<{ ok: boolean; detail: string }>
  refreshAccount: (connectionId: string) => Promise<{ ok: boolean; detail: string }>
  setAccountEnabled: (connectionId: string, enabled: boolean) => Promise<boolean>
  deleteAccount: (connectionId: string) => Promise<boolean>
  setAccountPolicy: (
    toolkit: string,
    update: { scope?: 'read' | 'write' | 'admin'; sync_enabled?: boolean }
  ) => Promise<boolean>
  syncAccount: (toolkit?: string, connectionId?: string) => Promise<boolean>
  getChat: (threadId?: string) => Promise<ChatPage>
  getChatThreads: (archived?: boolean) => Promise<ChatThread[]>
  createChatThread: (title?: string) => Promise<ChatThread | null>
  updateChatThread: (
    id: string,
    update: { title?: string; archived?: boolean }
  ) => Promise<ChatThread | null>
  setChatThreadModel: (
    id: string,
    selection: { provider?: string; model?: string; effort?: string }
  ) => Promise<ChatThread | null>
  deleteChatThread: (id: string) => Promise<boolean>
  uploadChatAttachment: (input: {
    threadId: string
    name: string
    mediaType: string
    data: string
  }) => Promise<ChatAttachment | null>
  removeChatAttachment: (id: string) => Promise<boolean>
  getChatAttachment: (id: string) => Promise<{ mediaType: string; data: string } | null>
  sendChat: (
    message: string,
    override?: { provider?: string; model?: string; effort?: string }
  ) => Promise<ChatReply | null>
  streamChat: (
    message: string,
    override?: { provider?: string; model?: string; effort?: string },
    context?: {
      threadId?: string
      attachmentIds?: string[]
      editMessageId?: number
      regenerateMessageId?: number
    }
  ) => Promise<boolean>
  cancelChat: () => Promise<boolean>
  onChatDelta: (listener: (event: Record<string, unknown>) => void) => () => void
  clearChat: (threadId?: string) => Promise<boolean>
  startChatDictation: (language?: string) => Promise<{ id: string } | null>
  pushChatDictationAudio: (
    id: string,
    pcm16: string
  ) => Promise<{ kind: string; text: string } | null>
  stopChatDictation: (id: string) => Promise<{ kind: string; text: string } | null>
  cancelChatDictation: (id: string) => Promise<boolean>
  copyText: (text: string) => Promise<boolean>
  getSchedules: () => Promise<SchedulePage | null>
  addSchedule: (body: {
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
  }) => Promise<SchedulePage | null>
  scheduleAction: (
    id: number,
    action: 'remove' | 'enable' | 'disable' | 'run'
  ) => Promise<SchedulePage | null>
  getPlugins: () => Promise<PluginPage | null>
  pluginAction: (
    name: string,
    action: 'install' | 'update' | 'remove'
  ) => Promise<PluginPage | null>
  getSetup: () => Promise<SetupPage | null>
  getHardware: () => Promise<HardwareAnswer | null>
  setHardware: (useGpu: boolean) => Promise<HardwareAnswer | null>
  installComponent: (name: string) => Promise<SetupPage | null>
  removeComponent: (name: string) => Promise<SetupPage | null>
  getSkillStore: () => Promise<{ skills: StoreSkill[]; sources: string[] } | null>
  reviewSkill: (repo: string, path: string) => Promise<SkillReview | null>
  installSkill: (staged: string) => Promise<{ ok: boolean; detail: string } | null>
  removeSkill: (name: string) => Promise<{ ok: boolean; detail: string } | null>
  getMcp: () => Promise<{ servers: McpServerRow[] } | null>
  runDoctor: () => Promise<DoctorReport | null>
  healDoctor: (includeConfirmed: boolean) => Promise<{ report: DoctorReport } | null>
  copyDiagnostics: () => Promise<string | null>
  getLogs: (
    subsystem: string
  ) => Promise<{ subsystem: string; lines: string[]; available: string[] } | null>
  getServices: () => Promise<ServiceReport[]>
  retryService: (name: string) => Promise<boolean>
  onServices: (listener: (reports: ServiceReport[]) => void) => () => void
  getProviders: () => Promise<ProviderPage | null>
  getUsage: (refresh?: boolean) => Promise<UsagePage | null>
  connectLocal: (
    name: string
  ) => Promise<{ connected: boolean; models: number; detail: string } | null>
  getModels: (options?: { provider?: string; refresh?: boolean }) => Promise<ModelPage | null>
  getUpstreams: (model?: string) => Promise<UpstreamPage | null>
  getVoices: () => Promise<VoicePage | null>
  getWake: () => Promise<WakeStatus | null>
  setProviderSettings: (values: Record<string, string>) => Promise<ProviderPage | null>
  getWorkspace: () => Promise<WorkspacePolicy | null>
  setWorkspace: (update: WorkspaceUpdate) => Promise<WorkspacePolicy | null>
  chooseFolder: () => Promise<string>
  answerQuestion: (id: string, answer: string) => Promise<boolean>
  saveSecret: (update: { id: string; name: string; value: string }) => Promise<boolean>
  startOauth: (name: string) => Promise<{ ok: boolean; detail: string }>
  pollOauth: (name: string) => Promise<Record<string, unknown> | null>
  disconnectProvider: (name: string) => Promise<ProviderPage | null>
  getIdentity: () => Promise<IdentityStatus | null>
  setIdentity: (update: { soul?: string; user?: string }) => Promise<IdentityStatus | null>
  getRoomState: () => Promise<{
    status: string
    result: { live: boolean; stale?: boolean; state: Record<string, unknown> } | null
    error: string | null
  } | null>
  resolveConfirmation: (token: string, decision: 'approve' | 'deny') => Promise<RuntimeStatus>
  previewAssistantState: (state: AssistantState) => void
  publishVoiceState: (state: AssistantState) => void
  setIslandSize: (size: { width: number; height: number }) => void
  setIslandInteractive: (interactive: boolean) => void
  minimizeWindow: () => void
  toggleMaximizeWindow: () => void
  closeWindow: () => void
  getWindowState: () => Promise<{ isMaximized: boolean }>
  onWindowState: (listener: (state: { isMaximized: boolean }) => void) => () => void
  setTranslucency: (intensity: number) => Promise<number>
}

export interface MarviBuildInfo {
  version: string
  commit: string
  buildTime: string
  platform: string
  arch: string
  updateChannel: string
}

declare global {
  interface Window {
    marvi: MarviDesktopApi
  }
}
