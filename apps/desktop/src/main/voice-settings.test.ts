import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { requiresVoiceWorkerRestart } from './voice-settings'

describe('voice setting lifecycle', () => {
  it('restarts the worker for recogniser and synthesis changes', () => {
    expect(requiresVoiceWorkerRestart({ MARVI_STT_ENGINE: 'kyutai-1b' })).toBe(true)
    expect(requiresVoiceWorkerRestart({ MARVI_STT_CHUNK: '1.0' })).toBe(true)
    expect(requiresVoiceWorkerRestart({ MARVI_TTS_ENGINE: 'kokoro' })).toBe(true)
  })

  it('leaves the worker alone for unrelated provider settings', () => {
    expect(requiresVoiceWorkerRestart({ MARVI_OPENROUTER_MODEL: 'model' })).toBe(false)
    expect(requiresVoiceWorkerRestart(null)).toBe(false)
    expect(requiresVoiceWorkerRestart(['MARVI_STT_ENGINE'])).toBe(false)
  })

  it('restarts the Agent only after the Gateway accepts the save', () => {
    const main = readFileSync(join(__dirname, 'index.ts'), 'utf8')
    expect(main).toContain(
      "if (page && requiresVoiceWorkerRestart(values)) supervisor?.retry('agent')"
    )
  })
})
