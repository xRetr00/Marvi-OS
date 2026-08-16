import type { AssistantState, RuntimeStatus } from '../shared/runtime'
import type { IslandPlacement } from '../main/island-window'

export interface MarviDesktopApi {
  getVersion: () => Promise<string>
  getBuildInfo: () => Promise<MarviBuildInfo>
  showMain: () => void
  getRuntime: () => Promise<RuntimeStatus>
  getDisplays: () => Promise<Array<{ id: number; label: string; primary: boolean }>>
  getIslandPlacement: () => Promise<IslandPlacement>
  setIslandPlacement: (placement: IslandPlacement) => Promise<IslandPlacement>
  onRuntime: (listener: (state: RuntimeStatus) => void) => () => void
  setYolo: (yolo: boolean) => Promise<RuntimeStatus>
  resolveConfirmation: (token: string, decision: 'approve' | 'deny') => Promise<RuntimeStatus>
  previewAssistantState: (state: AssistantState) => void
  setIslandSize: (size: { width: number; height: number }) => void
  setIslandInteractive: (interactive: boolean) => void
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
