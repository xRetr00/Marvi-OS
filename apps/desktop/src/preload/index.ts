import { contextBridge, ipcRenderer } from 'electron'
import type { AssistantState, RuntimeStatus } from '../shared/runtime'
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
  resolveConfirmation: (token: string, decision: 'approve' | 'deny'): Promise<RuntimeStatus> =>
    ipcRenderer.invoke('marvi:resolve-confirmation', token, decision),
  previewAssistantState: (state: AssistantState): void =>
    ipcRenderer.send('marvi:preview-assistant-state', state),
  publishVoiceState: (state: AssistantState): void =>
    ipcRenderer.send('marvi:voice-state', state),
  setIslandSize: (size: { width: number; height: number }): void =>
    ipcRenderer.send('marvi:island-size', size),
  setIslandInteractive: (interactive: boolean): void =>
    ipcRenderer.send('marvi:island-interactive', interactive)
}

contextBridge.exposeInMainWorld('marvi', marvi)
