import { atom } from 'nanostores'

import { persistString, storedString } from '../lib/storage'

export const APPEARANCE_STYLES = [
  'marvi',
  'anthropic-dark',
  'claude-code-dark',
  'midnight',
  'forest',
  'graphite'
] as const
export const FONT_FAMILIES = [
  'marvi-mono',
  'anthropic-sans',
  'anthropic-serif',
  'instrument-sans',
  'newsreader',
  'geist-mono'
] as const

export type AppearanceStyle = (typeof APPEARANCE_STYLES)[number]
export type FontFamily = (typeof FONT_FAMILIES)[number]

const STYLE_KEY = 'marvi.desktop.appearance.style.v1'
const FONT_KEY = 'marvi.desktop.appearance.font.v1'

function readChoice<T extends string>(key: string, choices: readonly T[], fallback: T): T {
  const stored = storedString(key)
  return stored && choices.includes(stored as T) ? (stored as T) : fallback
}

export function syncAppearanceStorage(key: string, value: string | null): boolean {
  if (key === STYLE_KEY && value && APPEARANCE_STYLES.includes(value as AppearanceStyle)) {
    $appearanceStyle.set(value as AppearanceStyle)
    return true
  }
  if (key === FONT_KEY && value && FONT_FAMILIES.includes(value as FontFamily)) {
    $fontFamily.set(value as FontFamily)
    return true
  }
  return false
}

export const $appearanceStyle = atom<AppearanceStyle>(
  typeof window === 'undefined' ? 'marvi' : readChoice(STYLE_KEY, APPEARANCE_STYLES, 'marvi')
)

export const $fontFamily = atom<FontFamily>(
  typeof window === 'undefined' ? 'marvi-mono' : readChoice(FONT_KEY, FONT_FAMILIES, 'marvi-mono')
)

export function setAppearanceStyle(style: AppearanceStyle): void {
  if (APPEARANCE_STYLES.includes(style)) $appearanceStyle.set(style)
}

export function setFontFamily(font: FontFamily): void {
  if (FONT_FAMILIES.includes(font)) $fontFamily.set(font)
}

export function applyAppearancePreferences(
  root: { dataset: Record<string, string | undefined> },
  style: AppearanceStyle,
  font: FontFamily
): void {
  root.dataset.appearance = style
  root.dataset.font = font
}

if (typeof document !== 'undefined') {
  const syncRoot = (): void => {
    applyAppearancePreferences(document.documentElement, $appearanceStyle.get(), $fontFamily.get())
  }
  $appearanceStyle.subscribe((style) => {
    syncRoot()
    persistString(STYLE_KEY, style)
  })
  $fontFamily.subscribe((font) => {
    syncRoot()
    persistString(FONT_KEY, font)
  })
  // The control center and Dynamic Island are separate renderer processes.
  // Storage events keep the always-on surface in step with live appearance
  // changes instead of requiring an application restart.
  window.addEventListener('storage', (event) => {
    syncAppearanceStorage(event.key ?? '', event.newValue)
  })
}
