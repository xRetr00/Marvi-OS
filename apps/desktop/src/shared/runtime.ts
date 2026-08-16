export const ASSISTANT_PHASES = [
  'ready',
  'wake',
  'listening',
  'thinking',
  'speaking',
  'action',
  'notification',
  'confirmation',
  'error'
] as const

export type AssistantPhase = (typeof ASSISTANT_PHASES)[number]
export type ComponentState = 'ready' | 'starting' | 'pending' | 'offline' | 'error'

export interface ConfirmationRequest {
  token: string
  action: string
  detail: string
  tool: string
  /** The exact arguments the approval is bound to. Echoed back to the Gateway verbatim. */
  arguments: Record<string, unknown>
}

export interface RoomEvent {
  id: number
  at: string
  type: string
  summary: string
}

export interface ConnectedAccount {
  toolkit: string
  status: string
  connected: boolean
  needsReconnect: boolean
}

export interface MemoryEntry {
  id: number
  kind: string
  subject: string
  body: string
  source: string
  trusted: boolean
  at: string
}

export interface MemoryPage {
  total: number
  entries: MemoryEntry[]
  summary: { total?: number; facts?: string[]; recent_events?: string[] }
}

export interface AuditEvent {
  at: string
  event: string
  tool: string
  arguments: Record<string, unknown>
  mode: 'confirm' | 'yolo'
  detail: string | null
}

export interface AssistantState {
  phase: AssistantPhase
  caption: string
  detail: string | null
  level: number
  yolo: boolean
  microphone: boolean
  camera: boolean
  confirmation: ConfirmationRequest | null
  /** Background room event. Rendered only while idle; never steals focus. */
  roomEvent: RoomEvent | null
}

export interface ComponentStatus {
  state: ComponentState
  detail: string
}

export interface RuntimeStatus {
  product: 'Marvi OS'
  version: string
  state: 'ready' | 'starting' | 'degraded' | 'offline' | 'error'
  components: Record<string, ComponentStatus>
  assistant: AssistantState
}

export const DEFAULT_ASSISTANT_STATE: AssistantState = {
  phase: 'ready',
  caption: 'Say Marvi',
  detail: null,
  level: 0,
  yolo: false,
  microphone: true,
  camera: true,
  confirmation: null,
  roomEvent: null
}

export const OFFLINE_RUNTIME: RuntimeStatus = {
  product: 'Marvi OS',
  version: 'unknown',
  state: 'offline',
  components: {
    gateway: { state: 'offline', detail: 'Marvi Gateway unavailable' },
    livekit: { state: 'offline', detail: 'Gateway unavailable' },
    voice: { state: 'offline', detail: 'Gateway unavailable' },
    vision: { state: 'offline', detail: 'Gateway unavailable' },
    accounts: { state: 'offline', detail: 'Gateway unavailable' },
    room: { state: 'offline', detail: 'Gateway unavailable' }
  },
  assistant: DEFAULT_ASSISTANT_STATE
}
