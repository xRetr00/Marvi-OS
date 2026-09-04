import { atom } from 'nanostores'

import type { VoicePage } from '../../../shared/runtime'

/**
 * The speech voices, shared by every picker that shows them.
 *
 * `VoicePicker` is rendered twice -- on the Voice page's rig and in Settings --
 * and each copy held its own `useState` and did its own fetch. So changing the
 * voice in one left the other showing the old one until something happened to
 * reload it, and the two disagreed about what Marvi was actually speaking with.
 *
 * The recogniser picker has been on a shared store for exactly this reason
 * (`recognisers.ts`), and this is the same store for the other half. One atom,
 * so both surfaces read the same answer and a change in either is a change in
 * both.
 */
export const $voices = atom<VoicePage | null>(null)

/** Re-read the Gateway's authoritative voice list and selection. */
export async function refreshVoices(): Promise<VoicePage | null> {
  const page = ((await window.marvi?.getVoices()) as VoicePage | null) ?? null
  $voices.set(page)
  return page
}

/**
 * Save a voice, and put the old one back if the Gateway refuses it.
 *
 * Optimistic, like `chooseRecogniser`: a picker that waits for a round trip
 * before moving feels broken, and a picker that moves and stays moved after a
 * failed save is lying.
 */
export async function chooseVoice(setting: string, next: string): Promise<boolean> {
  const before = $voices.get()
  if (!before) return false

  $voices.set({ ...before, selected: next })
  const saved = await window.marvi?.setProviderSettings({ [setting]: next })
  if (!saved) {
    $voices.set(before)
    return false
  }

  await refreshVoices()
  return true
}
