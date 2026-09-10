/**
 * The computer-activity poll, split from the island it feeds so that file
 * exports only components and keeps fast refresh.
 */

import { useEffect, useState } from 'react'

import type { ComputerStatus } from '../../../shared/computer'

/** How often to ask, by what the last answer was.
 *
 * A flat 250ms was four requests a second, for the life of the window,
 * whatever the answer -- including "no". In the retained logs that is 1,485
 * refusals of `/computer` in six minutes fifty-eight seconds, every one a 401
 * from a Gateway left over from an earlier launch, retried at the same pace
 * for as long as the app stayed open.
 *
 * A quarter of a second is the right pace for exactly one case: Marvi is
 * moving the mouse right now and the STOP button has to be live. Everything
 * else can wait, and a failing endpoint should be asked less often, not just
 * as often. */
const WATCHING = 250
const IDLE = 5_000
const OFF = 30_000

export function useComputerActivity(): ComputerStatus | null {
  const [status, setStatus] = useState<ComputerStatus | null>(null)
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    let revision: number | undefined
    // Doubles on each consecutive failure up to OFF, and resets on any answer.
    let cooling = IDLE
    const refresh = async (): Promise<void> => {
      let next: number = IDLE
      try {
        const answer = await window.marvi?.getComputer?.(revision)
        if (!answer) throw new Error('Gateway unavailable')
        if (alive) setStatus(answer)
        cooling = IDLE
        // Fast only while something is actually happening; slow when the
        // feature is switched off or not installed, which is the common case.
        // A current Gateway waits up to 25s for a revision change. Re-arm
        // immediately so a short action cannot disappear between idle polls.
        revision = answer.enabled && answer.installed ? answer.revision : undefined
        next =
          revision !== undefined
            ? 0
            : answer.active || answer.state === 'running' || answer.state === 'stopping'
              ? WATCHING
              : answer.enabled && answer.installed
                ? IDLE
                : OFF
      } catch {
        revision = undefined
        if (alive)
          setStatus((previous) =>
            previous && previous.state !== 'idle'
              ? { ...previous, active: false, state: 'unavailable' }
              : null
          )
        cooling = Math.min(cooling * 2, OFF)
        next = cooling
      } finally {
        // A hidden window is not watching anything move.
        if (alive)
          timer = setTimeout(
            () => {
              void refresh()
            },
            revision !== undefined
              ? next
              : typeof document !== 'undefined' && document.hidden
                ? OFF
                : next
          )
      }
    }
    void refresh()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [])
  return status
}
