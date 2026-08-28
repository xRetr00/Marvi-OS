import { atom } from 'nanostores'

import type {
  UpdateChannel,
  UpdateCheck,
  UpdateResult,
  UpdateStatus
} from '../../../shared/runtime'

export interface UpdateViewState {
  status: UpdateStatus | null
  result: UpdateResult | null
  check: UpdateCheck | null
  loading: boolean
  checkedAt: number | null
  handoff: 'idle' | 'starting' | 'failed'
}

export const $updateView = atom<UpdateViewState>({
  status: null,
  result: null,
  check: null,
  loading: false,
  checkedAt: null,
  handoff: 'idle'
})

let loading: Promise<void> | null = null

export function loadUpdateState(): Promise<void> {
  if (loading) return loading
  loading = (async () => {
    const [status, result] = await Promise.all([
      window.marvi?.getUpdateStatus(),
      window.marvi?.consumeUpdateResult()
    ])
    const current = $updateView.get()
    $updateView.set({
      ...current,
      status: status ?? null,
      result: result ?? current.result
    })
  })().finally(() => {
    loading = null
  })
  return loading
}

let checking: Promise<void> | null = null

export function checkForUpdate(): Promise<void> {
  if (checking) return checking
  $updateView.set({ ...$updateView.get(), loading: true })
  checking = (async () => {
    try {
      const check = await window.marvi?.checkForUpdate()
      $updateView.set({
        ...$updateView.get(),
        check: check ?? null,
        loading: false,
        checkedAt: Date.now()
      })
    } catch {
      $updateView.set({ ...$updateView.get(), loading: false, checkedAt: Date.now() })
    }
  })().finally(() => {
    checking = null
  })
  return checking
}

export async function setUpdateChannel(channel: UpdateChannel): Promise<void> {
  await window.marvi?.setUpdateChannel(channel)
  const current = $updateView.get()
  $updateView.set({
    ...current,
    check: null,
    status: current.status ? { ...current.status, channel } : current.status
  })
  await checkForUpdate()
}

/** Begin the native update handoff without hiding a failed launch. A successful
 * handoff exits the desktop a moment later; failure remains visible so the
 * user can retry or inspect the installed updater. */
export async function beginUpdate(): Promise<boolean> {
  if ($updateView.get().handoff === 'starting') return false
  $updateView.set({ ...$updateView.get(), handoff: 'starting' })
  try {
    const started = (await window.marvi?.startUpdate()) === true
    if (!started) $updateView.set({ ...$updateView.get(), handoff: 'failed' })
    return started
  } catch {
    $updateView.set({ ...$updateView.get(), handoff: 'failed' })
    return false
  }
}

export function clearUpdateHandoffFailure(): void {
  if ($updateView.get().handoff === 'failed') {
    $updateView.set({ ...$updateView.get(), handoff: 'idle' })
  }
}

const CHECK_INTERVAL_MS = 30 * 60 * 1000
const FOCUS_CHECK_MIN_AGE_MS = 5 * 60 * 1000
let stopPolling: (() => void) | null = null

/** Start the quiet desktop update lifecycle used by the status bar/About.
 * Checks once at startup, every 30 minutes, and after returning to a window
 * whose last result is at least five minutes old. Never opens a surface or
 * steals focus. */
export function startUpdatePolling(): () => void {
  if (stopPolling) return stopPolling

  void loadUpdateState().then(() => checkForUpdate())
  const onFocus = () => {
    const checkedAt = $updateView.get().checkedAt ?? 0
    if (Date.now() - checkedAt >= FOCUS_CHECK_MIN_AGE_MS) void checkForUpdate()
  }
  const timer = window.setInterval(() => void checkForUpdate(), CHECK_INTERVAL_MS)
  window.addEventListener('focus', onFocus)
  stopPolling = () => {
    window.clearInterval(timer)
    window.removeEventListener('focus', onFocus)
    stopPolling = null
  }
  return stopPolling
}
