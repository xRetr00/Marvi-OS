import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  cancelSettledRestart,
  requiresVoiceWorkerRestart,
  restartWhenSettled
} from './voice-settings'

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
    // The guarantee is the ordering: a save the Gateway rejected must not tear
    // down a working worker. The restart is scheduled rather than immediate
    // now (see `restartWhenSettled`), so this reads the condition rather than
    // one exact line.
    const main = readFileSync(join(__dirname, 'index.ts'), 'utf8')
    expect(main).toContain('if (page && requiresVoiceWorkerRestart(values)) {')
    expect(main).toContain("restartWhenSettled(() => supervisor?.retry('agent'))")
  })
})

describe('restarting the voice worker after a settings change', () => {
  afterEach(() => {
    cancelSettledRestart()
    vi.useRealTimers()
  })

  it('collapses a burst of edits into one restart', async () => {
    /**
     * The settings page writes one PUT per field, and every voice-related PUT
     * restarted the agent. Choosing an engine and then a voice for it is two
     * restarts; a few seconds of fiddling was four, each a 30-50 second
     * prewarm:
     *
     *     12:01:49  PUT  -> restart      12:02:16  PUT  -> restart
     *     12:01:54  PUT  -> restart      12:02:20  PUT  -> restart
     *     12:02:23  POST /livekit/session   <- Join, 3s into the last one
     *
     * That Join is the "no agent joined".
     */
    vi.useFakeTimers()
    let restarts = 0
    const restart = (): void => {
      restarts += 1
    }

    restartWhenSettled(restart, 4_000)
    await vi.advanceTimersByTimeAsync(1_000)
    restartWhenSettled(restart, 4_000)
    await vi.advanceTimersByTimeAsync(1_000)
    restartWhenSettled(restart, 4_000)

    // Still nothing: the person is mid-decision.
    expect(restarts).toBe(0)

    await vi.advanceTimersByTimeAsync(4_000)
    expect(restarts).toBe(1)
  })

  it('still restarts, once the edits stop', async () => {
    // The point is to delay it, never to lose it: a changed engine that never
    // restarts the worker is a setting that silently does nothing.
    vi.useFakeTimers()
    let restarts = 0

    restartWhenSettled(() => {
      restarts += 1
    }, 4_000)
    await vi.advanceTimersByTimeAsync(4_000)

    expect(restarts).toBe(1)
  })

  it('a later burst gets its own restart', async () => {
    vi.useFakeTimers()
    let restarts = 0
    const restart = (): void => {
      restarts += 1
    }

    restartWhenSettled(restart, 4_000)
    await vi.advanceTimersByTimeAsync(4_000)
    restartWhenSettled(restart, 4_000)
    await vi.advanceTimersByTimeAsync(4_000)

    expect(restarts).toBe(2)
  })
})
