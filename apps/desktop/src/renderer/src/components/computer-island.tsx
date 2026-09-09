import { useEffect, useState } from 'react'
import type { ComputerCommand, ComputerStatus } from '../../../shared/computer'

export function useComputerActivity(): ComputerStatus | null {
  const [status, setStatus] = useState<ComputerStatus | null>(null)
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    const refresh = async (): Promise<void> => {
      try {
        const next = await window.marvi?.getComputer?.()
        if (!next) throw new Error('Gateway unavailable')
        if (alive) setStatus(next)
      } catch {
        if (alive) setStatus(previous => previous && previous.state !== 'idle' ? { ...previous, active: false, state: 'unavailable' } : null)
      }
      finally { if (alive) timer = setTimeout(() => { void refresh() }, 250) }
    }
    void refresh()
    return () => { alive = false; clearTimeout(timer) }
  }, [])
  return status
}

export function ComputerIsland({ status }: { status: ComputerStatus }): React.JSX.Element {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const control = async (command: ComputerCommand): Promise<void> => {
    setBusy(true); setError(false)
    try { await window.marvi.computerControl(command) }
    catch { setError(true) }
    finally { setBusy(false) }
  }
  const paused = status.state === 'paused' || status.state === 'private'
  return <div className="dynamic-island island-confirmation" role="status" aria-live="polite">
    <div className="confirmation-copy">
      <small>{status.state === 'private' ? 'PRIVATE INPUT' : 'COMPUTER USE'}</small>
      <strong>{error || status.state === 'unavailable' ? 'Computer controls unavailable. Retry.' : status.state === 'stopping'
        ? 'Marvi is stopping computer use' : paused ? 'Computer use paused' : 'Marvi is using the computer'}</strong>
    </div>
    <div className="confirmation-actions">
      <button disabled={busy || status.state === 'stopping'} onClick={() => { void control(paused ? 'resume' : 'private') }}>{paused ? 'RESUME' : 'PRIVATE INPUT'}</button>
      {!paused && <button disabled={busy || status.state === 'stopping'} onClick={() => { void control('stop') }}>STOP</button>}
    </div>
  </div>
}
