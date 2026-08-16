import { contextBridge, ipcRenderer } from 'electron'
import type {
  AssistantState,
  AuditEvent,
  ConnectedAccount,
  MemoryPage,
  RoomEvent,
  RuntimeStatus
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
    const wrapped = (
      _event: Electron.IpcRendererEvent,
      state: { isMaximized: boolean }
    ): void => listener(state)
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
  getMemory: (): Promise<MemoryPage> => ipcRenderer.invoke('marvi:get-memory'),
  clearMemory: (): Promise<boolean> => ipcRenderer.invoke('marvi:clear-memory'),
  getAccounts: (): Promise<{
    available: boolean
    detail: string
    accounts: ConnectedAccount[]
  }> => ipcRenderer.invoke('marvi:get-accounts'),
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
