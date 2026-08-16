import { contextBridge, ipcRenderer } from 'electron'
import type {
  AssistantState,
  AuditEvent,
  ChatEntry,
  ChatReply,
  ConnectedAccount,
  IdentityStatus,
  InitiativeStatus,
  MindDecision,
  UpdateResult,
  UpdateStatus,
  MemoryPage,
  ProviderPage,
  RoomEvent,
  RuntimeStatus,
  ServiceReport
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
  sendChat: (message: string): Promise<ChatReply | null> =>
    ipcRenderer.invoke('marvi:send-chat', message),
  clearChat: (): Promise<boolean> => ipcRenderer.invoke('marvi:clear-chat'),
  getServices: (): Promise<ServiceReport[]> => ipcRenderer.invoke('marvi:get-services'),
  retryService: (name: string): Promise<boolean> => ipcRenderer.invoke('marvi:retry-service', name),
  onServices: (listener: (reports: ServiceReport[]) => void): (() => void) => {
    const handler = (_event: unknown, reports: ServiceReport[]): void => listener(reports)
    ipcRenderer.on('marvi:services', handler)
    return () => ipcRenderer.removeListener('marvi:services', handler)
  },
  getProviders: (): Promise<ProviderPage | null> => ipcRenderer.invoke('marvi:get-providers'),
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
