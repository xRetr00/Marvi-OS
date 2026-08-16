/**
 * Window translucency (see-through window), adapted from the Marvi/Hermes
 * desktop shell (MIT). One lever, 0–100. 0 = off (fully opaque, the default).
 * Higher = more of the desktop shows through the whole window — the main
 * process maps it to the native window opacity (`setOpacity`).
 *
 * The renderer owns the value and mirrors it to the main process over IPC.
 * Provenance: D:\hermes-agent\apps\desktop\src\store\translucency.ts
 * (see docs/UPSTREAM.md).
 */
import { atom } from 'nanostores'

import { persistString, storedString } from '../lib/storage'

const KEY = 'marvi.desktop.translucency.v1'

const clamp = (value: number): number => Math.min(100, Math.max(0, Math.round(value)))

const read = (): number => {
  const value = Number(storedString(KEY))
  return Number.isFinite(value) ? clamp(value) : 0
}

export const $translucency = atom<number>(typeof window === 'undefined' ? 0 : read())

export function setTranslucency(intensity: number): void {
  $translucency.set(clamp(intensity))
}

if (typeof window !== 'undefined') {
  $translucency.subscribe((intensity) => {
    persistString(KEY, String(intensity))
    void window.marvi?.setTranslucency(intensity)
  })
}
