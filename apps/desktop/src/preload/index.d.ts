import type {
  AssistantState,
  AuditEvent,
  ChatEntry,
  ChatReply,
  ConnectedAccount,
  DoctorReport,
  HardwareAnswer,
  McpServerRow,
  PluginPage,
  SchedulePage,
  SetupPage,
  SkillReview,
  StoreSkill,
  IdentityStatus,
  InitiativeStatus,
  MindDecision,
  UpdateChannel,
  UpdateCheck,
  UpdateResult,
  UpdateStatus,
  MemoryPage,
  ProviderPage,
  RoomEvent,
  RuntimeStatus,
  ServiceReport
} from '../shared/runtime'
import type { IslandPlacement } from '../main/island-window'

export interface MarviDesktopApi {
  getVersion: () => Promise<string>
  getBuildInfo: () => Promise<MarviBuildInfo>
  showMain: () => void
  getRuntime: () => Promise<RuntimeStatus>
  getVoiceSession: () => Promise<{ url: string; room: string; token: string }>
  getDisplays: () => Promise<Array<{ id: number; label: string; primary: boolean }>>
  getIslandPlacement: () => Promise<IslandPlacement>
  setIslandPlacement: (placement: IslandPlacement) => Promise<IslandPlacement>
  onRuntime: (listener: (state: RuntimeStatus) => void) => () => void
  setYolo: (yolo: boolean) => Promise<RuntimeStatus>
  getAudit: () => Promise<AuditEvent[]>
  getRoomEvents: () => Promise<RoomEvent[]>
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
  clearMemory: () => Promise<boolean>
  getAccounts: () => Promise<{
    available: boolean
    detail: string
    accounts: ConnectedAccount[]
  }>
  getChat: () => Promise<{ messages: ChatEntry[]; available: boolean }>
  sendChat: (message: string) => Promise<ChatReply | null>
  clearChat: () => Promise<boolean>
  getSchedules: () => Promise<SchedulePage | null>
  addSchedule: (body: {
    name: string
    when: string
    message?: string
    action?: string
    insist?: boolean
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
  setProviderSettings: (values: Record<string, string>) => Promise<ProviderPage | null>
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
