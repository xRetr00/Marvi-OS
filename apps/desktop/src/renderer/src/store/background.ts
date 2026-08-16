/**
 * Ambient backdrop store. The "Electric Gaze" animated ASCII background is a
 * vendored local asset (assets/background/electric-gaze.mp4) — the remote
 * 21st.dev URL it was fetched from is recorded in docs/UPSTREAM.md so it can
 * be re-fetched or swapped. Local-first: the shell never depends on a CDN at
 * runtime. Opacity is persisted per-machine.
 *
 * Pattern adapted from D:\hermes-agent\apps\desktop\src\store\background.ts.
 */
import { atom } from 'nanostores'

import { persistString, storedString } from '../lib/storage'

const MODE_KEY = 'marvi.desktop.background.v1'
const OPACITY_KEY = 'marvi.desktop.background.opacity.v1'

export const BACKGROUNDS = {
  electricGaze: {
    kind: 'video',
    label: 'ELECTRIC GAZE'
  },
  none: {
    kind: 'solid',
    label: 'OFF'
  }
} as const

export type BackgroundId = keyof typeof BACKGROUNDS

const isBackgroundId = (value: string | null): value is BackgroundId =>
  value !== null && value in BACKGROUNDS

const initialMode = typeof window === 'undefined' ? null : storedString(MODE_KEY)

const readOpacity = (): number => {
  const stored = storedString(OPACITY_KEY)
  if (stored === null) return 42
  const value = Number(stored)
  return Number.isFinite(value) ? Math.min(100, Math.max(0, Math.round(value))) : 42
}

export const $backgroundMode = atom<BackgroundId>(
  isBackgroundId(initialMode) ? initialMode : 'electricGaze'
)
export const $backgroundOpacity = atom<number>(typeof window === 'undefined' ? 42 : readOpacity())

export function setBackgroundMode(mode: BackgroundId): void {
  $backgroundMode.set(mode)
}

export function setBackgroundOpacity(opacity: number): void {
  $backgroundOpacity.set(Math.min(100, Math.max(0, Math.round(opacity))))
}

if (typeof window !== 'undefined') {
  $backgroundMode.subscribe((mode) => persistString(MODE_KEY, mode))
  $backgroundOpacity.subscribe((opacity) => persistString(OPACITY_KEY, String(opacity)))
}
