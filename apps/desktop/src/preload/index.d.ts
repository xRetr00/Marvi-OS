import type { AssistantState, AuditEvent, RoomEvent, RuntimeStatus } from '../shared/runtime'
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
