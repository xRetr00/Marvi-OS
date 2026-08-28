import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const status = { supported: true, inProgress: false, channel: 'dev' as const, root: 'D:\\Marvi-OS' }
const check = {
  channel: 'dev' as const,
  available: true,
  upToDate: false,
  current: 'a'.repeat(40),
  target: 'b'.repeat(40),
  targetRef: 'origin/main',
  behindBy: 1,
  commits: [{ sha: 'b'.repeat(40), summary: 'feat: update details', author: 'Marvi', at: 1 }]
}

describe('desktop update checks', () => {
  const listeners = new Map<string, () => void>()
  const api = {
    getUpdateStatus: vi.fn(async () => status),
    consumeUpdateResult: vi.fn(async () => null),
    checkForUpdate: vi.fn(async () => check),
    startUpdate: vi.fn(async () => false)
  }

  beforeEach(() => {
    vi.resetModules()
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-28T00:00:00Z'))
    listeners.clear()
    Object.values(api).forEach((mock) => mock.mockClear())
    vi.stubGlobal('window', {
      marvi: api,
      setInterval,
      clearInterval,
      addEventListener: vi.fn((name: string, handler: () => void) => listeners.set(name, handler)),
      removeEventListener: vi.fn((name: string) => listeners.delete(name))
    })
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('stores commit details and the check time', async () => {
    const { $updateView, checkForUpdate } = await import('./update-state')

    await checkForUpdate()

    expect($updateView.get().check?.commits[0].summary).toBe('feat: update details')
    expect($updateView.get().checkedAt).toBe(Date.now())
  })

  it('checks at startup and after a stale focus return', async () => {
    const { startUpdatePolling } = await import('./update-state')
    const stop = startUpdatePolling()
    await vi.waitFor(() => expect(api.checkForUpdate).toHaveBeenCalledTimes(1))

    listeners.get('focus')?.()
    expect(api.checkForUpdate).toHaveBeenCalledTimes(1)

    vi.advanceTimersByTime(5 * 60 * 1000)
    listeners.get('focus')?.()
    await vi.waitFor(() => expect(api.checkForUpdate).toHaveBeenCalledTimes(2))

    stop()
    expect(listeners.has('focus')).toBe(false)
  })

  it('keeps a failed native handoff visible instead of closing the surface', async () => {
    const { $updateView, beginUpdate } = await import('./update-state')

    await expect(beginUpdate()).resolves.toBe(false)

    expect($updateView.get().handoff).toBe('failed')
  })
})
