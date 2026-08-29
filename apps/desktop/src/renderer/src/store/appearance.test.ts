import { beforeEach, describe, expect, it } from 'vitest'

import {
  $appearanceStyle,
  $fontFamily,
  setAppearanceStyle,
  setFontFamily
} from './appearance'

describe('appearance preferences', () => {
  beforeEach(() => {
    setAppearanceStyle('marvi')
    setFontFamily('marvi-mono')
  })

  it('applies style and font choices to the document', () => {
    setAppearanceStyle('anthropic-dark')
    setFontFamily('anthropic-serif')

    expect($appearanceStyle.get()).toBe('anthropic-dark')
    expect($fontFamily.get()).toBe('anthropic-serif')
    expect(document.documentElement.dataset.appearance).toBe('anthropic-dark')
    expect(document.documentElement.dataset.font).toBe('anthropic-serif')
  })

  it('can select the compact code style independently from its font', () => {
    setAppearanceStyle('claude-code-dark')
    setFontFamily('anthropic-sans')

    expect($appearanceStyle.get()).toBe('claude-code-dark')
    expect($fontFamily.get()).toBe('anthropic-sans')
  })
})
