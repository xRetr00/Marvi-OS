import { contextBridge, ipcRenderer } from 'electron'
import type {
  AssistantState,
  AuditEvent,
  ChatEntry,
  ChatReply,
  ConnectedAccount,
  DoctorReport,
  HardwareAnswer,
  IdentityStatus,
  InitiativeStatus,
  McpServerRow,
  MemoryPage,
  MindDecision,
  ModelPage,
  PluginPage,
  ProviderPage,
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
  WakeStatus
} from '../shared/runtime'
import type { IslandPlacement } from '../main/island-window'

const marvi = {
  getVersion: (): Promise<string> => ipcRenderer.invoke('marvi:get-version'),
  getBuildInfo: (): Promise<{
    version: string
    commit: string
    buildTime: string
    platform: string
    arch: string
    updateChannel: string
  }> => ipcRenderer.invoke('marvi:get-build-info'),
  showMain: (): void => ipcRenderer.send('marvi:show-main'),
  minimizeWindow: (): void => ipcRenderer.send('marvi:window-minimize'),
  toggleMaximizeWindow: (): void => ipcRenderer.send('marvi:window-toggle-maximize'),
  closeWindow: (): void => ipcRenderer.send('marvi:window-close'),
  getWindowState: (): Promise<{ isMaximized: boolean }> =>
    ipcRenderer.invoke('marvi:get-window-state'),
  onWindowState: (listener: (state: { isMaximized: boolean }) => void): (() => void) => {
    const wrapped = (_event: Electron.IpcRendererEvent, state: { isMaximized: boolean }): void =>
      listener(state)
    ipcRenderer.on('marvi:window-state', wrapped)
    return () => ipcRenderer.removeListener('marvi:window-state', wrapped)
  },
  setTranslucency: (intensity: number): Promise<number> =>
    ipcRenderer.invoke('marvi:set-translucency', intensity),
  getRuntime: (): Promise<RuntimeStatus> => ipcRenderer.invoke('marvi:get-runtime'),
  getVoiceSession: (): Promise<{ url: string; room: string; token: string }> =>
    ipcRenderer.invoke('marvi:get-voice-session'),
  getDisplays: (): Promise<Array<{ id: number; label: string; primary: boolean }>> =>
    ipcRenderer.invoke('marvi:get-displays'),
  getIslandPlacement: (): Promise<IslandPlacement> =>
    ipcRenderer.invoke('marvi:get-island-placement'),
  setIslandPlacement: (placement: IslandPlacement): Promise<IslandPlacement> =>
    ipcRenderer.invoke('marvi:set-island-placement', placement),
  onRuntime: (listener: (state: RuntimeStatus) => void): (() => void) => {
    const wrapped = (_event: Electron.IpcRendererEvent, state: RuntimeStatus): void =>
      listener(state)
    ipcRenderer.on('marvi:runtime-state', wrapped)
    return () => ipcRenderer.removeListener('marvi:runtime-state', wrapped)
  },
  setYolo: (yolo: boolean): Promise<RuntimeStatus> => ipcRenderer.invoke('marvi:set-yolo', yolo),
  getAudit: (): Promise<AuditEvent[]> => ipcRenderer.invoke('marvi:get-audit'),
  getRoomEvents: (): Promise<RoomEvent[]> => ipcRenderer.invoke('marvi:get-room-events'),
  getInitiative: (): Promise<InitiativeStatus | null> => ipcRenderer.invoke('marvi:get-initiative'),
  setInitiative: (paused: boolean): Promise<InitiativeStatus | null> =>
    ipcRenderer.invoke('marvi:set-initiative', paused),
  getDecisions: (): Promise<{ decisions: MindDecision[]; events: unknown[] }> =>
    ipcRenderer.invoke('marvi:get-decisions'),
  getUpdateStatus: (): Promise<UpdateStatus> => ipcRenderer.invoke('marvi:get-update-status'),
  consumeUpdateResult: (): Promise<UpdateResult | null> =>
    ipcRenderer.invoke('marvi:consume-update-result'),
  getUpdateChannel: (): Promise<UpdateChannel> => ipcRenderer.invoke('marvi:get-update-channel'),
  setUpdateChannel: (channel: UpdateChannel): Promise<UpdateChannel> =>
    ipcRenderer.invoke('marvi:set-update-channel', channel),
  checkForUpdate: (): Promise<UpdateCheck> => ipcRenderer.invoke('marvi:check-update'),
  startUpdate: (): Promise<boolean> => ipcRenderer.invoke('marvi:start-update'),
  getMemory: (): Promise<MemoryPage> => ipcRenderer.invoke('marvi:get-memory'),
  clearMemory: (): Promise<boolean> => ipcRenderer.invoke('marvi:clear-memory'),
  getAccounts: (): Promise<{
    available: boolean
    detail: string
    accounts: ConnectedAccount[]
  }> => ipcRenderer.invoke('marvi:get-accounts'),
  getChat: (): Promise<{ messages: ChatEntry[]; available: boolean }> =>
    ipcRenderer.invoke('marvi:get-chat'),
  sendChat: (
    message: string,
    override?: { provider?: string; model?: string; effort?: string }
  ): Promise<ChatReply | null> => ipcRenderer.invoke('marvi:send-chat', message, override ?? {}),
  /**
   * Start a streamed turn. Events arrive on `onChatDelta`, not here.
   *
   * An IPC handler resolves once, which is the opposite of streaming, so the
   * turn is pushed and this only reports whether it began.
   */
  streamChat: (
    message: string,
    override?: { provider?: string; model?: string; effort?: string }
  ): Promise<boolean> => ipcRenderer.invoke('marvi:stream-chat', message, override ?? {}),
  /** Stop the turn in flight. Closes the provider connection, not just the UI. */
  cancelChat: (): Promise<boolean> => ipcRenderer.invoke('marvi:cancel-chat'),
  onChatDelta: (listener: (event: Record<string, unknown>) => void): (() => void) => {
    const wrapped = (_event: unknown, payload: Record<string, unknown>): void =>
      listener(payload)
    ipcRenderer.on('marvi:chat-delta', wrapped)
    return () => {
      ipcRenderer.removeListener('marvi:chat-delta', wrapped)
    }
  },
  clearChat: (): Promise<boolean> => ipcRenderer.invoke('marvi:clear-chat'),
  getSchedules: (): Promise<SchedulePage | null> => ipcRenderer.invoke('marvi:get-schedules'),
  addSchedule: (body: {
    name: string
    when: string
    message?: string
    action?: string
    insist?: boolean
  }): Promise<SchedulePage | null> => ipcRenderer.invoke('marvi:add-schedule', body),
  scheduleAction: (
    id: number,
    action: 'remove' | 'enable' | 'disable' | 'run'
  ): Promise<SchedulePage | null> => ipcRenderer.invoke('marvi:schedule-action', id, action),
  getPlugins: (): Promise<PluginPage | null> => ipcRenderer.invoke('marvi:get-plugins'),
  pluginAction: (
    name: string,
    action: 'install' | 'update' | 'remove'
  ): Promise<PluginPage | null> => ipcRenderer.invoke('marvi:plugin-action', name, action),
  getSetup: (): Promise<SetupPage | null> => ipcRenderer.invoke('marvi:get-setup'),
  getHardware: (): Promise<HardwareAnswer | null> => ipcRenderer.invoke('marvi:get-hardware'),
  setHardware: (useGpu: boolean): Promise<HardwareAnswer | null> =>
    ipcRenderer.invoke('marvi:set-hardware', useGpu),
  installComponent: (name: string): Promise<SetupPage | null> =>
    ipcRenderer.invoke('marvi:install-component', name),
  removeComponent: (name: string): Promise<SetupPage | null> =>
    ipcRenderer.invoke('marvi:remove-component', name),
  getSkillStore: (): Promise<{ skills: StoreSkill[]; sources: string[] } | null> =>
    ipcRenderer.invoke('marvi:get-skill-store'),
  reviewSkill: (repo: string, path: string): Promise<SkillReview | null> =>
    ipcRenderer.invoke('marvi:review-skill', repo, path),
  installSkill: (staged: string): Promise<{ ok: boolean; detail: string } | null> =>
    ipcRenderer.invoke('marvi:install-skill', staged),
  removeSkill: (name: string): Promise<{ ok: boolean; detail: string } | null> =>
    ipcRenderer.invoke('marvi:remove-skill', name),
  getMcp: (): Promise<{ servers: McpServerRow[] } | null> => ipcRenderer.invoke('marvi:get-mcp'),
  runDoctor: (): Promise<DoctorReport | null> => ipcRenderer.invoke('marvi:run-doctor'),
  healDoctor: (includeConfirmed: boolean): Promise<{ report: DoctorReport } | null> =>
    ipcRenderer.invoke('marvi:heal-doctor', includeConfirmed),
  copyDiagnostics: (): Promise<string | null> => ipcRenderer.invoke('marvi:copy-diagnostics'),
  getLogs: (
    subsystem: string
  ): Promise<{ subsystem: string; lines: string[]; available: string[] } | null> =>
    ipcRenderer.invoke('marvi:get-logs', subsystem),
  getServices: (): Promise<ServiceReport[]> => ipcRenderer.invoke('marvi:get-services'),
  retryService: (name: string): Promise<boolean> => ipcRenderer.invoke('marvi:retry-service', name),
  onServices: (listener: (reports: ServiceReport[]) => void): (() => void) => {
    const handler = (_event: unknown, reports: ServiceReport[]): void => listener(reports)
    ipcRenderer.on('marvi:services', handler)
    return () => ipcRenderer.removeListener('marvi:services', handler)
  },
  getProviders: (): Promise<ProviderPage | null> => ipcRenderer.invoke('marvi:get-providers'),
  /** Probe a local provider and mark it connected only if it answers. */
  connectLocal: (
    name: string
  ): Promise<{ connected: boolean; models: number; detail: string } | null> =>
    ipcRenderer.invoke('marvi:connect-local', name),
  getModels: (options?: { provider?: string; refresh?: boolean }): Promise<ModelPage | null> =>
    ipcRenderer.invoke('marvi:get-models', options ?? {}),
  getUpstreams: (model?: string): Promise<UpstreamPage | null> =>
    ipcRenderer.invoke('marvi:get-upstreams', model ?? ''),
  getVoices: (): Promise<VoicePage | null> => ipcRenderer.invoke('marvi:get-voices'),
  getWake: (): Promise<WakeStatus | null> => ipcRenderer.invoke('marvi:get-wake'),
  setProviderSettings: (values: Record<string, string>): Promise<ProviderPage | null> =>
    ipcRenderer.invoke('marvi:set-provider-settings', values),
  startOauth: (name: string): Promise<{ ok: boolean; detail: string }> =>
    ipcRenderer.invoke('marvi:start-oauth', name),
  pollOauth: (name: string): Promise<Record<string, unknown> | null> =>
    ipcRenderer.invoke('marvi:poll-oauth', name),
  disconnectProvider: (name: string): Promise<ProviderPage | null> =>
    ipcRenderer.invoke('marvi:disconnect-provider', name),
  getIdentity: (): Promise<IdentityStatus | null> => ipcRenderer.invoke('marvi:get-identity'),
  setIdentity: (update: { soul?: string; user?: string }): Promise<IdentityStatus | null> =>
    ipcRenderer.invoke('marvi:set-identity', update),
  getRoomState: (): Promise<{
    status: string
    result: { live: boolean; stale?: boolean; state: Record<string, unknown> } | null
    error: string | null
  } | null> => ipcRenderer.invoke('marvi:get-room-state'),
  resolveConfirmation: (token: string, decision: 'approve' | 'deny'): Promise<RuntimeStatus> =>
    ipcRenderer.invoke('marvi:resolve-confirmation', token, decision),
  previewAssistantState: (state: AssistantState): void =>
    ipcRenderer.send('marvi:preview-assistant-state', state),
  publishVoiceState: (state: AssistantState): void => ipcRenderer.send('marvi:voice-state', state),
  setIslandSize: (size: { width: number; height: number }): void =>
    ipcRenderer.send('marvi:island-size', size),
  setIslandInteractive: (interactive: boolean): void =>
    ipcRenderer.send('marvi:island-interactive', interactive)
}

contextBridge.exposeInMainWorld('marvi', marvi)
