import { atom } from 'nanostores'

import { persistString, storedString } from '../lib/storage'

export const APPEARANCE_STYLES = ['marvi', 'anthropic-dark', 'claude-code-dark'] as const
export const FONT_FAMILIES = ['marvi-mono', 'anthropic-sans', 'anthropic-serif'] as const

export type AppearanceStyle = (typeof APPEARANCE_STYLES)[number]
export type FontFamily = (typeof FONT_FAMILIES)[number]

const STYLE_KEY = 'marvi.desktop.appearance.style.v1'
const FONT_KEY = 'marvi.desktop.appearance.font.v1'

function readChoice<T extends string>(key: string, choices: readonly T[], fallback: T): T {
  const stored = storedString(key)
  return stored && choices.includes(stored as T) ? (stored as T) : fallback
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

if (typeof document !== 'undefined') {
  $appearanceStyle.subscribe((style) => {
    document.documentElement.dataset.appearance = style
    persistString(STYLE_KEY, style)
  })
  $fontFamily.subscribe((font) => {
    document.documentElement.dataset.font = font
    persistString(FONT_KEY, font)
  })
}
