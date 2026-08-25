import { beforeEach, describe, expect, it, vi } from 'vitest'

describe('the one-shot announcer', () => {
  beforeEach(() => {
    vi.stubGlobal('window', {
      marvi: {
        readAloud: vi.fn(async () => undefined),
        stopReadAloud: vi.fn(async () => true)
      }
    })
  })

  it('reads Chat without opening a Voice room', async () => {
    const { readAloudWithMarvi } = await import('./announcer')
    await readAloudWithMarvi('A settled Chat response.')
    expect(window.marvi.readAloud).toHaveBeenCalledWith('A settled Chat response.')
  })

  it('stops the Gateway playback', async () => {
    const { stopMarviReadAloud } = await import('./announcer')
    await stopMarviReadAloud()
    expect(window.marvi.stopReadAloud).toHaveBeenCalled()
  })
})
