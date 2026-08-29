import { beforeEach, describe, expect, it } from 'vitest'

import {
  $appearanceStyle,
  $fontFamily,
  applyAppearancePreferences,
  setAppearanceStyle,
  setFontFamily
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
})
