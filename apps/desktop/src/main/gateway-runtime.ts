import {
  ASSISTANT_PHASES,
  OFFLINE_RUNTIME,
  type AssistantState,
  type ComponentState,
  type RuntimeStatus
} from '../shared/runtime'

const COMPONENT_STATES = new Set<ComponentState>([
  'ready',
  'starting',
  'pending',
  'offline',
  'error'
])
const RUNTIME_STATES = new Set<RuntimeStatus['state']>([
  'ready',
  'starting',
  'degraded',
  'offline',
  'error'
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

export function normalizeRuntimeStatus(value: unknown): RuntimeStatus | null {
  if (!isRecord(value) || value.product !== 'Marvi OS' || typeof value.version !== 'string') {
    return null
  }
  if (
    typeof value.state !== 'string' ||
    !RUNTIME_STATES.has(value.state as RuntimeStatus['state'])
  ) {
    return null
  }
  if (!isRecord(value.components) || !isRecord(value.assistant)) return null

  const assistant = value.assistant
  if (
    typeof assistant.phase !== 'string' ||
    !ASSISTANT_PHASES.includes(assistant.phase as AssistantState['phase']) ||
    typeof assistant.caption !== 'string' ||
    typeof assistant.level !== 'number' ||
    typeof assistant.yolo !== 'boolean'
  ) {
    return null
  }

  const model = isRecord(value.model) ? value.model : {}
  const components: RuntimeStatus['components'] = {}
  for (const [name, component] of Object.entries(value.components)) {
    if (
      !isRecord(component) ||
      typeof component.state !== 'string' ||
      !COMPONENT_STATES.has(component.state as ComponentState) ||
      typeof component.detail !== 'string'
    ) {
      return null
    }
    components[name] = {
      state: component.state as ComponentState,
      detail: component.detail
    }
  }

  let confirmation: AssistantState['confirmation'] = null
  if (assistant.confirmation !== null && assistant.confirmation !== undefined) {
    if (
      !isRecord(assistant.confirmation) ||
      typeof assistant.confirmation.token !== 'string' ||
      typeof assistant.confirmation.action !== 'string' ||
      typeof assistant.confirmation.detail !== 'string' ||
      typeof assistant.confirmation.tool !== 'string' ||
      !isRecord(assistant.confirmation.arguments)
    ) {
      return null
    }
    confirmation = {
      token: assistant.confirmation.token,
      action: assistant.confirmation.action,
      detail: assistant.confirmation.detail,
      tool: assistant.confirmation.tool,
      arguments: assistant.confirmation.arguments
    }
  }

  let roomEvent: AssistantState['roomEvent'] = null
  if (assistant.room_event !== null && assistant.room_event !== undefined) {
    if (
      !isRecord(assistant.room_event) ||
      typeof assistant.room_event.id !== 'number' ||
      typeof assistant.room_event.at !== 'string' ||
      typeof assistant.room_event.type !== 'string' ||
      typeof assistant.room_event.summary !== 'string'
    ) {
      return null
    }
    roomEvent = {
      id: assistant.room_event.id,
      at: assistant.room_event.at,
      type: assistant.room_event.type,
      summary: assistant.room_event.summary
    }
  }

  return {
    product: 'Marvi OS',
    version: value.version,
    state: value.state as RuntimeStatus['state'],
    components,
    assistant: {
      phase: assistant.phase as AssistantState['phase'],
      caption: assistant.caption,
      detail: typeof assistant.detail === 'string' ? assistant.detail : null,
      level: Math.max(0, Math.min(1, assistant.level)),
      yolo: assistant.yolo,
      heard: typeof assistant.heard === 'string' ? assistant.heard : '',
      spoken: typeof assistant.spoken === 'string' ? assistant.spoken : '',
      confirmation,
      roomEvent
    },
    model: {
      llm: typeof model.llm === 'string' ? model.llm : '',
      stt: typeof model.stt === 'string' ? model.stt : '',
      tts: typeof model.tts === 'string' ? model.tts : ''
    }
  }
}

export function offlineRuntime(version: string): RuntimeStatus {
  return { ...OFFLINE_RUNTIME, version }
}

const LIVE_PHASES = new Set<AssistantState['phase']>([
  'wake',
  'listening',
  'thinking',
  'speaking'
])

/** Reconcile the slow Gateway snapshot with the renderer's high-rate voice state.
 * Confirmations and terminal states always win, including an authoritative null:
 * retaining the old request here left the Island interactive after every outcome. */
export function reconcileRuntimeStatus(
  current: RuntimeStatus,
  gateway: RuntimeStatus
): RuntimeStatus {
  const keepLiveRenderer =
    LIVE_PHASES.has(current.assistant.phase) &&
    (gateway.assistant.phase === 'ready' || LIVE_PHASES.has(gateway.assistant.phase))

  if (!keepLiveRenderer) return gateway
  return {
    ...gateway,
    assistant: {
      ...current.assistant,
      yolo: gateway.assistant.yolo,
      confirmation: gateway.assistant.confirmation,
      roomEvent: gateway.assistant.roomEvent
    }
  }
}

/** A dead Gateway must remove stale controls immediately while retaining the
 * last authoritative mode marker so YOLO never becomes visually ambiguous. */
export function offlineRuntimeFrom(version: string, current: RuntimeStatus): RuntimeStatus {
  const offline = offlineRuntime(version)
  return {
    ...offline,
    assistant: { ...offline.assistant, yolo: current.assistant.yolo }
  }
}
