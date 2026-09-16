import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { HotkeysWindow, KeyCombo } from './hotkeys-window'
import { HOTKEY_DEFINITIONS } from '../../../shared/hotkeys'

describe('the keyboard shortcuts window', () => {
  const markup = renderToStaticMarkup(<HotkeysWindow onClose={() => {}} />)

  it('lists every shortcut Marvi has, with a way to change and clear each', () => {
    for (const definition of HOTKEY_DEFINITIONS) {
      expect(markup).toContain(definition.label)
      expect(markup).toContain(definition.description)
      expect(markup).toContain(`Change the shortcut for ${definition.label}`)
      expect(markup).toContain(`Turn off the shortcut for ${definition.label}`)
    }
    expect(markup).toContain('Restore defaults')
  })

  it('is a dialog that says these work outside Marvi', () => {
    expect(markup).toContain('aria-modal="true"')
    expect(markup).toContain('anywhere in Windows')
  })

  it('paints a combination as keys, and nothing as Off', () => {
    expect(renderToStaticMarkup(<KeyCombo accelerator="Alt+Shift+M" />)).toBe(
      '<span class="hotkeys-combo"><kbd>Alt</kbd><kbd>Shift</kbd><kbd>M</kbd></span>'
    )
    expect(renderToStaticMarkup(<KeyCombo accelerator="" />)).toContain('Off')
  })
})
