import { describe, expect, it } from 'vitest'

import { normalizeRuntimeStatus } from './gateway-runtime'

const valid = {
  product: 'Marvi OS',
  version: '0.1.0-test',
  state: 'starting',
  components: { gateway: { state: 'ready', detail: 'online' } },
  assistant: {
    phase: 'thinking',
    caption: 'Considering room context',
    detail: null,
    level: 0.3,
    yolo: false,
    confirmation: null
  }
}

describe('normalizeRuntimeStatus', () => {
  it('accepts and clamps a valid Gateway runtime snapshot', () => {
    expect(
      normalizeRuntimeStatus({ ...valid, assistant: { ...valid.assistant, level: 8 } })
    ).toMatchObject({ assistant: { phase: 'thinking', level: 1 } })
  })

  it('rejects invalid external state instead of trusting the loopback response', () => {
    expect(
      normalizeRuntimeStatus({ ...valid, assistant: { ...valid.assistant, phase: 'dreaming' } })
    ).toBeNull()
    expect(
      normalizeRuntimeStatus({ ...valid, components: { gateway: { state: 'magic' } } })
    ).toBeNull()
  })

  it('keeps the exact arguments an approval will be bound to', () => {
    const confirmation = {
      token: 'token-1',
      action: 'Change the room light',
      detail: 'Change the room light (brightness=55, on=True)',
      tool: 'room_set_light',
      arguments: { on: true, brightness: 55 }
    }

    expect(
      normalizeRuntimeStatus({ ...valid, assistant: { ...valid.assistant, confirmation } })
    ).toMatchObject({ assistant: { confirmation } })
  })

  it('maps a background room event onto its own channel', () => {
    const normalized = normalizeRuntimeStatus({
      ...valid,
      assistant: {
        ...valid.assistant,
        phase: 'listening',
        room_event: {
          id: 42,
          at: '2026-08-16T03:41:00Z',
          type: 'mode_changed',
          summary: 'mode changed to sleep'
        }
      }
    })

    // The event rides alongside the voice phase; it never replaces it.
    expect(normalized?.assistant.phase).toBe('listening')
    expect(normalized?.assistant.roomEvent).toEqual({
      id: 42,
      at: '2026-08-16T03:41:00Z',
      type: 'mode_changed',
      summary: 'mode changed to sleep'
    })
  })

  it('rejects a malformed room event rather than rendering junk', () => {
    expect(
      normalizeRuntimeStatus({
        ...valid,
        assistant: { ...valid.assistant, room_event: { id: 'nope', summary: 'x' } }
      })
    ).toBeNull()
  })

  it('rejects a confirmation that arrives without its bound arguments', () => {
    expect(
      normalizeRuntimeStatus({
        ...valid,
        assistant: {
          ...valid.assistant,
          confirmation: { token: 't', action: 'a', detail: 'd', tool: 'room_set_light' }
        }
      })
    ).toBeNull()
  })
})
