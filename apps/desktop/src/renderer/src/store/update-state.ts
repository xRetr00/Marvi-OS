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
}

export const $updateView = atom<UpdateViewState>({
  status: null,
  result: null,
  check: null,
  loading: false
})

let loading: Promise<void> | null = null

export function loadUpdateState(): Promise<void> {
  if (loading) return loading
  loading = (async () => {
    const [status, result] = await Promise.all([
      window.marvi?.getUpdateStatus(),
      window.marvi?.consumeUpdateResult()
    ])
    $updateView.set({ ...$updateView.get(), status: status ?? null, result: result ?? null })
  })().finally(() => {
    loading = null
  })
  return loading
}

export async function checkForUpdate(): Promise<void> {
  $updateView.set({ ...$updateView.get(), loading: true })
  const check = await window.marvi?.checkForUpdate()
  $updateView.set({ ...$updateView.get(), check: check ?? null, loading: false })
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
