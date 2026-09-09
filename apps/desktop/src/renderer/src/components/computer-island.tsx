import { useEffect, useState } from 'react'
import type { ComputerCommand, ComputerStatus } from '../../../shared/computer'

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
    // Doubles on each consecutive failure up to OFF, and resets on any answer.
    let cooling = IDLE
    const refresh = async (): Promise<void> => {
      let next: number = IDLE
      try {
        const answer = await window.marvi?.getComputer?.()
        if (!answer) throw new Error('Gateway unavailable')
        if (alive) setStatus(answer)
        cooling = IDLE
        // Fast only while something is actually happening; slow when the
        // feature is switched off or not installed, which is the common case.
        next = answer.active || answer.state === 'running' || answer.state === 'stopping'
          ? WATCHING
          : answer.enabled && answer.installed
            ? IDLE
            : OFF
      } catch {
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
            typeof document !== 'undefined' && document.hidden ? OFF : next
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

export function ComputerIsland({ status }: { status: ComputerStatus }): React.JSX.Element {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const control = async (command: ComputerCommand): Promise<void> => {
    setBusy(true)
    setError(false)
    try {
      await window.marvi.computerControl(command)
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }
  const paused = status.state === 'paused' || status.state === 'private'
  return (
    <div className="dynamic-island island-confirmation" role="status" aria-live="polite">
      <div className="confirmation-copy">
        <small>{status.state === 'private' ? 'PRIVATE INPUT' : 'COMPUTER USE'}</small>
        <strong>
          {error || status.state === 'unavailable'
            ? 'Computer controls unavailable. Retry.'
            : status.state === 'unknown'
              ? 'Computer action outcome unknown'
            : status.state === 'stopping'
              ? 'Marvi is stopping computer use'
              : paused
                ? 'Computer use paused'
                : 'Marvi is using the computer'}
        </strong>
      </div>
      <div className="confirmation-actions">
        <button
          disabled={busy || status.state === 'stopping'}
          onClick={() => {
            void control(paused ? 'resume' : 'private')
          }}
        >
          {paused ? 'RESUME' : 'PRIVATE INPUT'}
        </button>
        {!paused && (
          <button
            disabled={busy || status.state === 'stopping'}
            onClick={() => {
              void control('stop')
            }}
          >
            STOP
          </button>
        )}
      </div>
    </div>
  )
}
