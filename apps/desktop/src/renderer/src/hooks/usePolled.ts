/**
 * One timer per endpoint, however many components want the answer.
 *
 * Every card that wanted a piece of live state opened its own `setInterval`
 * and asked the Gateway itself. Three components wanted the wake word at
 * 1.5 s, 3 s and 4 s; the activity card wanted 1.2 s; and all of it ran again
 * in the second window. `gateway.log` for one idle afternoon is 959 KB and
 * almost none of it is anything happening:
 *
 *     13:51:04,785  "GET /voice/wake HTTP/1.1" 200 OK
 *     13:51:04,893  "GET /runtime HTTP/1.1" 200 OK
 *     13:51:05,591  "GET /voice/wake HTTP/1.1" 200 OK
 *     13:51:05,998  "GET /voice/activity HTTP/1.1" 200 OK
 *
 * Three things are wrong there and this fixes all three.
 *
 * **One reader, many subscribers.** Components asking for the same thing share
 * one request. The feed runs at the shortest interval anybody asked for and
 * everybody gets every answer, so a card that wanted 4 s updates is not made
 * worse by a neighbour that wanted 1.5 s.
 *
 * **Nothing while nobody is looking.** A hidden window polls nothing. On
 * becoming visible the feed reads once immediately, so a returning window is
 * current rather than up to an interval stale.
 *
 * **One request at a time.** A tick arriving while the last read is still out
 * is skipped rather than stacked. A slow Gateway used to accumulate requests
 * it was already too busy to answer, which is the shape of a stall becoming an
 * outage.
 *
 * The machinery is plain functions rather than hook internals so it can be
 * tested for what actually went wrong -- how many requests leave the window --
 * without a DOM and a renderer.
 */

import { useEffect, useState } from 'react'

interface Subscriber {
  every: number
  deliver: (value: unknown) => void
}

interface Feed {
  read: () => Promise<unknown>
  subscribers: Map<symbol, Subscriber>
  latest: unknown
  timer: ReturnType<typeof setInterval> | null
  every: number
  inflight: boolean
}

const feeds = new Map<string, Feed>()

/** Hidden means hidden; in a test environment there may be no document. */
function looking(): boolean {
  return typeof document === 'undefined' || !document.hidden
}

async function pull(feed: Feed): Promise<void> {
  if (feed.inflight || !looking()) return
  feed.inflight = true
  try {
    const value = await feed.read()
    // Only on an answer. A failed poll leaves the last good state on screen
    // rather than blanking every card each time the Gateway restarts.
    if (value) {
      feed.latest = value
      for (const { deliver } of feed.subscribers.values()) deliver(value)
    }
  } catch {
    // Same reason: a card that cannot load shows nothing, never an error.
  } finally {
    feed.inflight = false
  }
}

function retime(key: string, feed: Feed): void {
  const idle = feed.subscribers.size === 0
  if (idle || !looking()) {
    if (feed.timer !== null) clearInterval(feed.timer)
    feed.timer = null
    if (idle) feeds.delete(key)
    return
  }
  const wanted = Math.min(...[...feed.subscribers.values()].map((s) => s.every))
  if (feed.timer !== null && feed.every === wanted) return
  if (feed.timer !== null) clearInterval(feed.timer)
  feed.every = wanted
  feed.timer = setInterval(() => void pull(feed), wanted)
}

/**
 * Ask for `key` every `every` ms at the slowest, and be told each answer.
 *
 * Returns the unsubscribe. `key` names the thing being read, not the caller:
 * two subscribers passing the same key share one request, so it has to be the
 * same endpoint behind both.
 */
export function subscribe(
  key: string,
  read: () => Promise<unknown>,
  every: number,
  deliver: (value: unknown) => void
): () => void {
  const me = Symbol(key)
  let feed = feeds.get(key)
  if (!feed) {
    feed = { read, subscribers: new Map(), latest: null, timer: null, every, inflight: false }
    feeds.set(key, feed)
  }
  feed.subscribers.set(me, { every, deliver })
  retime(key, feed)
  // Whatever the feed already knows, at once -- a card mounting into a running
  // feed should not wait a whole interval to show anything.
  if (feed.latest) deliver(feed.latest)
  else void pull(feed)

  return () => {
    const still = feeds.get(key)
    if (!still) return
    still.subscribers.delete(me)
    retime(key, still)
  }
}

/** What a feed already knows, for a subscriber that has only just arrived. */
export function known(key: string): unknown {
  return feeds.get(key)?.latest ?? null
}

/** Every feed reconsiders itself: stopped while hidden, read on return. */
export function onVisibilityChange(): void {
  for (const [key, feed] of feeds) {
    retime(key, feed)
    if (looking()) void pull(feed)
  }
}

/**
 * Read `key` right now, ahead of its own interval, and tell every subscriber.
 *
 * `onVisibilityChange` already does this trick for a window coming back from
 * hidden -- read once immediately rather than show what could be a whole
 * interval stale. Nothing did the equivalent for a visible window: the
 * calendar polls once a minute so a card sitting open does not hammer the
 * Gateway for a month view that rarely changes, and STT/TTS engine choices
 * were not on this registry at all, so changing one from a settings page
 * across the app and coming back here meant waiting out the interval or
 * restarting -- there was no button that meant "ask again, now."
 *
 * Goes through `pull`, so a refresh pressed while a read is already out does
 * not stack a second request behind it -- it rides the one already in
 * flight, same as a tick landing mid-request would. A no-op, resolving at
 * once, for a key nobody currently subscribes to: there is no feed to read
 * and nobody waiting on the answer.
 */
export function refresh(key: string): Promise<void> {
  const feed = feeds.get(key)
  return feed ? pull(feed) : Promise.resolve()
}

/** Every live feed, refreshed at once -- a single "sync now" that does not
 * need to know which keys happen to be subscribed to right now. */
export function refreshAll(): Promise<void[]> {
  return Promise.all([...feeds.values()].map((feed) => pull(feed)))
}

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', onVisibilityChange)
}

/** The latest answer for `key`, shared with everyone else asking for it. */
export function usePolled<T>(key: string, read: () => Promise<unknown>, ms: number): T | null {
  const [value, setValue] = useState<T | null>(() => (known(key) as T) ?? null)

  useEffect(
    () => subscribe(key, read, ms, (v) => setValue(v as T)),
    // `read` is a fresh closure on every render and would restart the feed on
    // each one; the key is what identifies what is being read.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key, ms]
  )

  return value
}
