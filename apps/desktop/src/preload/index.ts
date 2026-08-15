import { contextBridge, ipcRenderer } from 'electron'

const marvi = {
  getVersion: (): Promise<string> => ipcRenderer.invoke('marvi:get-version'),
  showMain: (): void => ipcRenderer.send('marvi:show-main')
}

contextBridge.exposeInMainWorld('marvi', marvi)
