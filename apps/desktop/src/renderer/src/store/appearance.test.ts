import { beforeEach, describe, expect, it } from 'vitest'

import {
  APPEARANCE_STYLES,
  FONT_FAMILIES,
  $appearanceStyle,
  $fontFamily,
  applyAppearancePreferences,
  setAppearanceStyle,
  setFontFamily,
  syncAppearanceStorage
} from './appearance'

describe('appearance preferences', () => {
  beforeEach(() => {
    setAppearanceStyle('marvi')
    setFontFamily('marvi-mono')
  })

  it('keeps independent style and font choices', () => {
    const root = { dataset: {} as Record<string, string | undefined> }
    setAppearanceStyle('anthropic-dark')
    setFontFamily('anthropic-serif')
    applyAppearancePreferences(root, $appearanceStyle.get(), $fontFamily.get())

    expect($appearanceStyle.get()).toBe('anthropic-dark')
    expect($fontFamily.get()).toBe('anthropic-serif')
    expect(root.dataset).toEqual({
      appearance: 'anthropic-dark',
      font: 'anthropic-serif'
    })
  })

  it('can select the compact code style independently from its font', () => {
    setAppearanceStyle('claude-code-dark')
    setFontFamily('anthropic-sans')

    expect($appearanceStyle.get()).toBe('claude-code-dark')
    expect($fontFamily.get()).toBe('anthropic-sans')
  })

  it('offers the complete local theme and font catalog', () => {
    expect(APPEARANCE_STYLES).toEqual([
      'marvi',
      'anthropic-dark',
      'claude-code-dark',
      'midnight',
      'forest',
      'graphite'
    ])
    expect(FONT_FAMILIES).toEqual([
      'marvi-mono',
      'anthropic-sans',
      'anthropic-serif',
      'instrument-sans',
      'newsreader',
      'geist-mono'
    ])
  })

  it('synchronizes valid cross-window appearance changes', () => {
    expect(syncAppearanceStorage('marvi.desktop.appearance.style.v1', 'forest')).toBe(true)
    expect(syncAppearanceStorage('marvi.desktop.appearance.font.v1', 'newsreader')).toBe(true)
    expect($appearanceStyle.get()).toBe('forest')
    expect($fontFamily.get()).toBe('newsreader')
    expect(syncAppearanceStorage('marvi.desktop.appearance.style.v1', 'unknown')).toBe(false)
  })
})
