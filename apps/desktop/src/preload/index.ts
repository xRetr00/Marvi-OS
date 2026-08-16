import { contextBridge, ipcRenderer } from 'electron'

const marvi = {
  getVersion: (): Promise<string> => ipcRenderer.invoke('marvi:get-version'),
  showMain: (): void => ipcRenderer.send('marvi:show-main'),
  pushIslandState: (state: unknown): void => ipcRenderer.send('marvi:island-state', state),
  onIslandState: (listener: (state: unknown) => void): (() => void) => {
    const wrapped = (_event: Electron.IpcRendererEvent, state: unknown): void => listener(state)
    ipcRenderer.on('marvi:island-state', wrapped)
    return () => ipcRenderer.removeListener('marvi:island-state', wrapped)
  },
  setIslandSize: (size: { width: number; height: number }): void =>
    ipcRenderer.send('marvi:island-size', size),
  setIslandInteractive: (interactive: boolean): void =>
    ipcRenderer.send('marvi:island-interactive', interactive)
}

contextBridge.exposeInMainWorld('marvi', marvi)
