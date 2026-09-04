/**
 * How many requests leave the window, which is the whole point of the thing.
 *
 * `gateway.log` for one idle afternoon was 959 KB of `/voice/wake` and
 * `/voice/activity` at several a second, because every card that wanted live
 * state opened its own interval and asked the Gateway itself -- three times
 * over for the wake word alone, and again in the second window.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

import { onVisibilityChange, refresh, refreshAll, subscribe } from './usePolled'

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

describe('a button that means "ask again, now"', () => {
  it('reads immediately rather than waiting out the interval', async () => {
    vi.useFakeTimers()
    const { read, calls } = counter()
    const off = subscribe('models', read, 60_000, () => {})
    await vi.advanceTimersByTimeAsync(0)
    const before = calls()

    // Nowhere near the next tick, and the calendar-style feeds this exists
    // for are on intervals exactly this long -- the whole point is not to
    // have to wait it out.
    await refresh('models')
    expect(calls()).toBe(before + 1)
    off()
  })

  it('delivers the answer to every subscriber, not just the one that asked', async () => {
    vi.useFakeTimers()
    const { read } = counter()
    const seenA: unknown[] = []
    const seenB: unknown[] = []
    const a = subscribe('providers', read, 60_000, (v) => seenA.push(v))
    const b = subscribe('providers', read, 60_000, (v) => seenB.push(v))
    await vi.advanceTimersByTimeAsync(0)
    const before = seenA.length

    await refresh('providers')
    expect(seenA.length).toBe(before + 1)
    expect(seenB.length).toBe(before + 1)
    a()
    b()
  })

  it('does not stack a second request behind one already out', async () => {
    vi.useFakeTimers()
    let started = 0
    let release = (): void => {}
    const read = async (): Promise<unknown> => {
      started += 1
      await new Promise<void>((resolve) => {
        release = resolve
      })
      return { ok: true }
    }
    const off = subscribe('usage-refresh', read, 60_000, () => {})
    await vi.advanceTimersByTimeAsync(0)
    expect(started).toBe(1)

    // Pressing the button while the Gateway is still owed an answer must not
    // be how a slow Gateway becomes a Gateway sent two requests for the same
    // thing.
    const pending = refresh('usage-refresh')
    expect(started).toBe(1)

    release()
    await pending
    off()
  })

  it('is a no-op for a key nobody is subscribed to', async () => {
    vi.useFakeTimers()
    // Nothing ever subscribed to this key, so there is no feed in the
    // registry at all -- refresh must not throw reaching for one.
    await expect(refresh('nobody-listening')).resolves.toBeUndefined()
  })

  it('refreshAll reads every live feed at once', async () => {
    vi.useFakeTimers()
    const first = counter()
    const second = counter()
    const a = subscribe('feed-one', first.read, 60_000, () => {})
    const b = subscribe('feed-two', second.read, 60_000, () => {})
    await vi.advanceTimersByTimeAsync(0)
    const beforeOne = first.calls()
    const beforeTwo = second.calls()

    await refreshAll()
    expect(first.calls()).toBe(beforeOne + 1)
    expect(second.calls()).toBe(beforeTwo + 1)
    a()
    b()
  })
})
