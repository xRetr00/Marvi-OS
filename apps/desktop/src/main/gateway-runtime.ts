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
    typeof assistant.yolo !== 'boolean' ||
    typeof assistant.microphone !== 'boolean' ||
    typeof assistant.camera !== 'boolean'
  ) {
    return null
  }

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
      microphone: assistant.microphone,
      camera: assistant.camera,
      confirmation,
      roomEvent
    }
  }
}

export function offlineRuntime(version: string): RuntimeStatus {
  return { ...OFFLINE_RUNTIME, version }
}
