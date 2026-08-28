import { contextBridge, ipcRenderer } from 'electron'
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
  MemoryImportPreview,
  MemoryImportRequest,
  MemoryImportSources,
  MemoryImportResult,
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
  SkillsPage,
  SkillProposal,
  StoreSkill,
  UpdateChannel,
  UpdateCheck,
  UpdateResult,
  UpdateStatus,
  UpstreamPage,
  VoicePage,
  LanguagePolicy,
  LanguageUpdate,
  MemoryPolicy,
  MemorySettingsUpdate,
  WakeStatus,
  WorkspacePolicy,
  WorkspaceUpdate
} from '../shared/runtime'
import type { IslandPlacement } from '../main/island-window'
import type { PetPreferences } from '../main/pet-window'

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
  onNavigate: (listener: (page: 'Voice' | 'Activity') => void): (() => void) => {
    const wrapped = (_event: Electron.IpcRendererEvent, page: 'Voice' | 'Activity'): void =>
      listener(page)
    ipcRenderer.on('marvi:navigate', wrapped)
    return () => ipcRenderer.removeListener('marvi:navigate', wrapped)
  },
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
  setVoiceSessionActive: (active: boolean): Promise<boolean> =>
    ipcRenderer.invoke('marvi:set-voice-session-active', active),
  readAloud: (text: string): Promise<void> => ipcRenderer.invoke('marvi:read-aloud', text),
  stopReadAloud: (): Promise<boolean> => ipcRenderer.invoke('marvi:stop-read-aloud'),
  getDisplays: (): Promise<Array<{ id: number; label: string; primary: boolean }>> =>
    ipcRenderer.invoke('marvi:get-displays'),
  getIslandPlacement: (): Promise<IslandPlacement> =>
    ipcRenderer.invoke('marvi:get-island-placement'),
  setIslandPlacement: (placement: IslandPlacement): Promise<IslandPlacement> =>
    ipcRenderer.invoke('marvi:set-island-placement', placement),
  getPetPreferences: (): Promise<PetPreferences> => ipcRenderer.invoke('marvi:get-pet-preferences'),
  setPetPreferences: (preferences: PetPreferences): Promise<PetPreferences> =>
    ipcRenderer.invoke('marvi:set-pet-preferences', preferences),
  onPetLookDirection: (listener: (direction: number | null) => void): (() => void) => {
    const wrapped = (_event: Electron.IpcRendererEvent, direction: number | null): void =>
      listener(direction)
    ipcRenderer.on('marvi:pet-look-direction', wrapped)
    return () => ipcRenderer.removeListener('marvi:pet-look-direction', wrapped)
  },
  onRuntime: (listener: (state: RuntimeStatus) => void): (() => void) => {
    const wrapped = (_event: Electron.IpcRendererEvent, state: RuntimeStatus): void =>
      listener(state)
    ipcRenderer.on('marvi:runtime-state', wrapped)
    return () => ipcRenderer.removeListener('marvi:runtime-state', wrapped)
  },
  /**
   * The wake word fired. Either Marvi was just started by it, or she was
   * already open and the listener handed the argument to this instance -- the
   * renderer does not need to know which, because both mean the same thing:
   * join, now, as though Join had been pressed.
   */
  onWakeJoin: (listener: () => void): (() => void) => {
    const wrapped = (): void => listener()
    ipcRenderer.on('marvi:wake-join', wrapped)
    return () => ipcRenderer.removeListener('marvi:wake-join', wrapped)
  },
  /** True when this launch was the wake word's doing, for a renderer that was
   *  not listening yet when it happened. */
  consumeWakeLaunch: (): Promise<boolean> => ipcRenderer.invoke('marvi:consume-wake-launch'),
  getWakeAutostart: (): Promise<{ autostart: boolean; running: boolean }> =>
    ipcRenderer.invoke('marvi:get-wake-autostart'),
  setWakeAutostart: (
    enabled: boolean,
    device?: string
  ): Promise<{ autostart: boolean; running: boolean }> =>
    ipcRenderer.invoke('marvi:set-wake-autostart', enabled, device ?? ''),
  setYolo: (yolo: boolean): Promise<RuntimeStatus> => ipcRenderer.invoke('marvi:set-yolo', yolo),
  getAudit: (): Promise<AuditEvent[]> => ipcRenderer.invoke('marvi:get-audit'),
  getRoomEvents: (): Promise<RoomEvent[]> => ipcRenderer.invoke('marvi:get-room-events'),
  getAuxiliary: (): Promise<AuxiliaryPage | null> => ipcRenderer.invoke('marvi:get-auxiliary'),
  getRoomHealth: (): Promise<Record<string, unknown> | null> =>
    ipcRenderer.invoke('marvi:get-room-health'),
  getFaceLibrary: (): Promise<FaceLibrary | null> => ipcRenderer.invoke('marvi:get-face-library'),
  getRoomVisionPreview: (): Promise<RoomVisionPreview | null> =>
    ipcRenderer.invoke('marvi:get-room-vision-preview'),
  roomCommand: (
    tool: string,
    args: Record<string, unknown>
  ): Promise<{ status: string; error?: string; token?: string | null }> =>
    ipcRenderer.invoke('marvi:room-command', tool, args),
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
  getMemoryGraph: (mode: MemoryGraphMode): Promise<MemoryGraphPage> =>
    ipcRenderer.invoke('marvi:get-memory-graph', mode),
  clearMemory: (): Promise<boolean> => ipcRenderer.invoke('marvi:clear-memory'),
  getAccounts: (): Promise<AccountPage> => ipcRenderer.invoke('marvi:get-accounts'),
  getAccountCatalog: (): Promise<AccountToolkit[]> =>
    ipcRenderer.invoke('marvi:get-account-catalog'),
  configureAccounts: (apiKey: string): Promise<{ ok: boolean; detail: string }> =>
    ipcRenderer.invoke('marvi:configure-accounts', apiKey),
  connectAccount: (toolkit: string): Promise<{ ok: boolean; detail: string }> =>
    ipcRenderer.invoke('marvi:connect-account', toolkit),
  refreshAccount: (connectionId: string): Promise<{ ok: boolean; detail: string }> =>
    ipcRenderer.invoke('marvi:refresh-account', connectionId),
  setAccountEnabled: (connectionId: string, enabled: boolean): Promise<boolean> =>
    ipcRenderer.invoke('marvi:set-account-enabled', connectionId, enabled),
  deleteAccount: (connectionId: string): Promise<boolean> =>
    ipcRenderer.invoke('marvi:delete-account', connectionId),
  setAccountPolicy: (
    toolkit: string,
    update: { scope?: 'read' | 'write' | 'admin'; sync_enabled?: boolean }
  ): Promise<boolean> => ipcRenderer.invoke('marvi:set-account-policy', toolkit, update),
  syncAccount: (toolkit?: string, connectionId?: string): Promise<boolean> =>
    ipcRenderer.invoke('marvi:sync-account', toolkit ?? '', connectionId ?? ''),
  getChat: (threadId?: string): Promise<ChatPage> => ipcRenderer.invoke('marvi:get-chat', threadId),
  getChatThreads: (archived = false): Promise<ChatThread[]> =>
    ipcRenderer.invoke('marvi:get-chat-threads', archived),
  createChatThread: (title?: string): Promise<ChatThread | null> =>
    ipcRenderer.invoke('marvi:create-chat-thread', title),
  updateChatThread: (
    id: string,
    update: { title?: string; archived?: boolean }
  ): Promise<ChatThread | null> => ipcRenderer.invoke('marvi:update-chat-thread', id, update),
  setChatThreadModel: (
    id: string,
    selection: { provider?: string; model?: string; effort?: string }
  ): Promise<ChatThread | null> => ipcRenderer.invoke('marvi:set-chat-thread-model', id, selection),
  deleteChatThread: (id: string): Promise<boolean> =>
    ipcRenderer.invoke('marvi:delete-chat-thread', id),
  uploadChatAttachment: (input: {
    threadId: string
    name: string
    mediaType: string
    data: string
  }): Promise<ChatAttachment | null> => ipcRenderer.invoke('marvi:upload-chat-attachment', input),
  removeChatAttachment: (id: string): Promise<boolean> =>
    ipcRenderer.invoke('marvi:remove-chat-attachment', id),
  getChatAttachment: (id: string): Promise<{ mediaType: string; data: string } | null> =>
    ipcRenderer.invoke('marvi:get-chat-attachment', id),
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
    override?: { provider?: string; model?: string; effort?: string },
    context?: {
      threadId?: string
      attachmentIds?: string[]
      editMessageId?: number
      regenerateMessageId?: number
    }
  ): Promise<boolean> =>
    ipcRenderer.invoke('marvi:stream-chat', message, override ?? {}, context ?? {}),
  /** Stop the turn in flight. Closes the provider connection, not just the UI. */
  cancelChat: (): Promise<boolean> => ipcRenderer.invoke('marvi:cancel-chat'),
  onChatDelta: (listener: (event: Record<string, unknown>) => void): (() => void) => {
    const wrapped = (_event: unknown, payload: Record<string, unknown>): void => listener(payload)
    ipcRenderer.on('marvi:chat-delta', wrapped)
    return () => {
      ipcRenderer.removeListener('marvi:chat-delta', wrapped)
    }
  },
  clearChat: (threadId?: string): Promise<boolean> =>
    ipcRenderer.invoke('marvi:clear-chat', threadId),
  startChatDictation: (language?: string): Promise<{ id: string } | null> =>
    ipcRenderer.invoke('marvi:start-chat-dictation', language),
  pushChatDictationAudio: (
    id: string,
    pcm16: string
  ): Promise<{ kind: string; text: string } | null> =>
    ipcRenderer.invoke('marvi:push-chat-dictation-audio', id, pcm16),
  stopChatDictation: (id: string): Promise<{ kind: string; text: string } | null> =>
    ipcRenderer.invoke('marvi:stop-chat-dictation', id),
  cancelChatDictation: (id: string): Promise<boolean> =>
    ipcRenderer.invoke('marvi:cancel-chat-dictation', id),
  copyText: (text: string): Promise<boolean> => ipcRenderer.invoke('marvi:copy-text', text),
  getSchedules: (): Promise<SchedulePage | null> => ipcRenderer.invoke('marvi:get-schedules'),
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
  getInstalledSkills: (): Promise<SkillsPage | null> =>
    ipcRenderer.invoke('marvi:get-installed-skills'),
  pinSkill: (name: string, pinned: boolean): Promise<unknown> =>
    ipcRenderer.invoke('marvi:pin-skill', name, pinned),
  archiveSkill: (name: string): Promise<unknown> => ipcRenderer.invoke('marvi:archive-skill', name),
  restoreSkill: (name: string): Promise<unknown> =>
    ipcRenderer.invoke('marvi:restore-skill', name),
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
  getUsage: (refresh = true): Promise<UsagePage | null> =>
    ipcRenderer.invoke('marvi:get-usage', refresh),
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
  getMemorySettings: (): Promise<MemoryPolicy | null> =>
    ipcRenderer.invoke('marvi:get-memory-settings'),
  setMemorySettings: (update: MemorySettingsUpdate): Promise<MemoryPolicy | null> =>
    ipcRenderer.invoke('marvi:set-memory-settings', update),
  getSkillProposal: (): Promise<SkillProposal | null> =>
    ipcRenderer.invoke('marvi:get-skill-proposal'),
  /** True when the gateway settled it. Declining writes nothing. */
  settleSkillProposal: (accept: boolean): Promise<boolean> =>
    ipcRenderer.invoke('marvi:settle-skill-proposal', accept),
  getLanguage: (): Promise<LanguagePolicy | null> => ipcRenderer.invoke('marvi:get-language'),
  setLanguage: (update: LanguageUpdate): Promise<LanguagePolicy | null> =>
    ipcRenderer.invoke('marvi:set-language', update),
  getWorkspace: (): Promise<WorkspacePolicy | null> => ipcRenderer.invoke('marvi:get-workspace'),
  setWorkspace: (update: WorkspaceUpdate): Promise<WorkspacePolicy | null> =>
    ipcRenderer.invoke('marvi:set-workspace', update),
  /** The native folder picker. Empty string when the user cancelled. */
  chooseFolder: (): Promise<string> => ipcRenderer.invoke('marvi:choose-folder'),
  /** Memory files to import. Empty when the user cancelled. */
  chooseMemoryFiles: (): Promise<string[]> => ipcRenderer.invoke('marvi:choose-memory-files'),
  getImportSources: (): Promise<MemoryImportSources | null> =>
    ipcRenderer.invoke('marvi:get-import-sources'),
  getHonchoWorkspaces: (): Promise<{ workspaces: string[]; detail: string } | null> =>
    ipcRenderer.invoke('marvi:get-honcho-workspaces'),
  previewMemoryImport: (request: MemoryImportRequest): Promise<MemoryImportPreview | null> =>
    ipcRenderer.invoke('marvi:preview-memory-import', request),
  importMemories: (request: MemoryImportRequest): Promise<MemoryImportResult | null> =>
    ipcRenderer.invoke('marvi:import-memories', request),
  answerQuestion: (id: string, answer: string): Promise<boolean> =>
    ipcRenderer.invoke('marvi:answer-question', { id, answer }),
  /** A credential the user typed. Goes to the settings store and stops there. */
  saveSecret: (update: { id: string; name: string; value: string }): Promise<boolean> =>
    ipcRenderer.invoke('marvi:save-secret', update),
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
