/**
 * How many requests leave the window, which is the whole point of the thing.
 *
 * `gateway.log` for one idle afternoon was 959 KB of `/voice/wake` and
 * `/voice/activity` at several a second, because every card that wanted live
 * state opened its own interval and asked the Gateway itself -- three times
 * over for the wake word alone, and again in the second window.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

import { onVisibilityChange, subscribe } from './usePolled'

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

function counter(): { read: () => Promise<unknown>; calls: () => number } {
  let calls = 0
  return {
    read: async () => {
      calls += 1
      return { n: calls }
    },
    calls: () => calls
  }
}

describe('one timer per endpoint', () => {
  it('asks once for everybody who wants the same thing', async () => {
    vi.useFakeTimers()
    const { read, calls } = counter()
    const seen: unknown[] = []
    const a = subscribe('wake', read, 3000, (v) => seen.push(v))
    const b = subscribe('wake', read, 4000, (v) => seen.push(v))

    // The first read happens on subscribe; the second subscriber is handed
    // what the feed already knows rather than asking again.
    await vi.advanceTimersByTimeAsync(0)
    expect(calls()).toBe(1)

    await vi.advanceTimersByTimeAsync(3000)
    expect(calls()).toBe(2)
    // Three components used to mean three requests. Both were told.
    expect(seen.length).toBeGreaterThanOrEqual(3)
    a()
    b()
  })

  it('runs at the shortest interval anybody asked for', async () => {
    vi.useFakeTimers()
    const { read, calls } = counter()
    const slow = subscribe('activity', read, 4000, () => {})
    const fast = subscribe('activity', read, 1000, () => {})
    await vi.advanceTimersByTimeAsync(0)
    const start = calls()

    await vi.advanceTimersByTimeAsync(4000)
    // Four ticks at the impatient subscriber's rate, not one at the patient
    // one's: a card wanting 4 s updates is not made worse by its neighbour.
    expect(calls() - start).toBe(4)

    // And when the impatient one leaves, the feed slows back down.
    fast()
    const before = calls()
    await vi.advanceTimersByTimeAsync(4000)
    expect(calls() - before).toBe(1)
    slow()
  })

  it('stops entirely when the last subscriber goes', async () => {
    vi.useFakeTimers()
    const { read, calls } = counter()
    const off = subscribe('runtime', read, 1000, () => {})
    await vi.advanceTimersByTimeAsync(0)
    off()
    const after = calls()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(calls()).toBe(after)
  })
})

describe('a slow Gateway', () => {
  it('is not sent a second request while it owes an answer', async () => {
    vi.useFakeTimers()
    let started = 0
    // Initialised to a no-op rather than null: assigned only inside the
    // promise executor, TypeScript narrows it to `never` and the call below
    // stops compiling.
    let release = (): void => {}
    const read = async (): Promise<unknown> => {
      started += 1
      await new Promise<void>((resolve) => {
        release = resolve
      })
      return { ok: true }
    }
    const off = subscribe('usage', read, 500, () => {})
    await vi.advanceTimersByTimeAsync(0)
    expect(started).toBe(1)

    // Ten ticks pass with the first request still out. Stacking them is how a
    // stall becomes an outage: the Gateway is already too busy to answer.
    await vi.advanceTimersByTimeAsync(5000)
    expect(started).toBe(1)

    release()
    await vi.advanceTimersByTimeAsync(500)
    expect(started).toBe(2)
    off()
  })

  it('keeps the last good answer when a read throws', async () => {
    vi.useFakeTimers()
    let fail = false
    const seen: unknown[] = []
    const read = async (): Promise<unknown> => {
      if (fail) throw new Error('gateway restarting')
      return { good: true }
    }
    const off = subscribe('voices', read, 1000, (v) => seen.push(v))
    await vi.advanceTimersByTimeAsync(0)
    fail = true
    await vi.advanceTimersByTimeAsync(3000)
    // Nothing new delivered, and nothing blanked: a card that cannot load
    // shows what it had, never an error over the top of the orb.
    expect(seen).toEqual([{ good: true }])
    off()
  })
})

describe('a window nobody is looking at', () => {
  it('polls nothing, and is current again the moment it is', async () => {
    vi.useFakeTimers()
    const { read, calls } = counter()
    // No DOM in this environment, and the module asks `document.hidden` at
    // call time, so the smallest possible stand-in is enough.
    let hiddenNow = false
    ;(globalThis as { document?: unknown }).document = {
      get hidden() {
        return hiddenNow
      },
      addEventListener: () => {}
    }
    const hidden = { mockReturnValue: (v: boolean) => (hiddenNow = v) }
    const off = subscribe('wake-visible', read, 1000, () => {})
    await vi.advanceTimersByTimeAsync(0)

    hidden.mockReturnValue(true)
    onVisibilityChange()
    const asleep = calls()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(calls()).toBe(asleep)

    hidden.mockReturnValue(false)
    onVisibilityChange()
    await vi.advanceTimersByTimeAsync(0)
    // Read at once on return rather than up to an interval stale.
    expect(calls()).toBe(asleep + 1)
    off()
    delete (globalThis as { document?: unknown }).document
  })
})
