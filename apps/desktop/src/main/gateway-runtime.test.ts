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
    microphone: true,
    camera: true,
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
})
