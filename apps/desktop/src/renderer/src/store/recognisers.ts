import { atom } from 'nanostores'

import type { RecogniserPage } from '../../../shared/runtime'

export const $recognisers = atom<RecogniserPage | null>(null)

/** Refresh both picker surfaces from the Gateway's authoritative selection. */
export async function refreshRecognisers(): Promise<RecogniserPage | null> {
  const page = (await window.marvi?.getRecognisers()) ?? null
  $recognisers.set(page)
  return page
}

/** Save one valid installed recogniser and reconcile the optimistic selection. */
export async function chooseRecogniser(next: string): Promise<boolean> {
  const before = $recognisers.get()
  const engine = before?.engines.find((item) => item.id === next)
  if (!before || !engine?.available) return false

  $recognisers.set({ ...before, selected: next, missing: false })
  const saved = await window.marvi?.setProviderSettings({ [before.setting]: next })
  if (!saved) {
    $recognisers.set(before)
    return false
  }

  await refreshRecognisers()
  return true
}
