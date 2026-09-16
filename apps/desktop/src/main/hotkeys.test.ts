import { mkdtempSync, readFileSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { describe, expect, it } from 'vitest'

import {
  HOTKEY_ACTIONS,
  acceleratorFrom,
  clashes,
  defaults,
  normalize,
  tidy,
  why
} from '../shared/hotkeys'
import { hotkeysPath, load, save, withBinding } from './hotkeys'

const press = (key: string, held: Partial<Record<'alt' | 'ctrl' | 'shift' | 'meta', boolean>> = {}, code?: string) => ({
  key,
  code,
  altKey: Boolean(held.alt),
  ctrlKey: Boolean(held.ctrl),
  shiftKey: Boolean(held.shift),
  metaKey: Boolean(held.meta)
})

describe('accelerators', () => {
  it('spells one combination one way', () => {
    expect(tidy('alt+shift+m')).toBe('Alt+Shift+M')
    expect(tidy('Shift + ALT + m')).toBe('Alt+Shift+M')
    expect(tidy('ctrl+alt+Delete')).toBe('Control+Alt+Delete')
    expect(tidy('win+space')).toBe('Super+Space')
    expect(tidy('cmdorctrl+f5')).toBe('CommandOrControl+F5')
  })

  it('refuses what would break the machine or Electron', () => {
    expect(tidy('M')).toBe('') // a bare letter would swallow it everywhere
    expect(tidy('Alt+Shift+M+K')).toBe('') // two keys is not an accelerator
    expect(tidy('Alt+Shift')).toBe('') // modifiers only
    expect(tidy('Alt+Nonsense')).toBe('')
    expect(why('M')).toContain('modifier')
    expect(why('Alt+Nonsense')).toContain('cannot register')
    expect(why('Alt+M')).toBe('')
  })

  it('reads a key press the way the person meant it', () => {
    expect(acceleratorFrom(press('M', { alt: true, shift: true }, 'KeyM'))).toBe('Alt+Shift+M')
    // Shift+5 reports '%', but the person means the 5 key.
    expect(acceleratorFrom(press('%', { ctrl: true, shift: true }, 'Digit5'))).toBe(
      'Control+Shift+5'
    )
    expect(acceleratorFrom(press(' ', { ctrl: true }, 'Space'))).toBe('Control+Space')
    expect(acceleratorFrom(press('Shift', { shift: true }))).toBe('') // modifiers alone
    expect(acceleratorFrom(press('M', {}, 'KeyM'))).toBe('') // no modifier: refused
  })
})

describe('the stored set', () => {
  it('gives every action a default, and honours the old summon variable', () => {
    const fresh = defaults()
    expect(Object.keys(fresh).sort()).toEqual([...HOTKEY_ACTIONS].sort())
    expect(fresh.summon).toBe('Alt+Shift+M')
    expect(defaults({ MARVI_SUMMON_HOTKEY: 'ctrl+space' }).summon).toBe('Control+Space')
    expect(defaults({ MARVI_SUMMON_HOTKEY: 'off' }).summon).toBe('')
  })

  it('keeps a deliberate off, repairs junk, and ignores unknown actions', () => {
    const stored = normalize({ summon: '', stop: 'alt+shift+s', chat: 'nonsense', fly: 'Alt+F' })
    expect(stored.summon).toBe('') // switched off on purpose
    expect(stored.stop).toBe('Alt+Shift+S')
    expect(stored.chat).toBe('Alt+Shift+C') // junk falls back to the default
    expect('fly' in stored).toBe(false)
    expect(normalize('not an object')).toEqual(defaults())
  })

  it('notices two actions on one combination', () => {
    const bindings = { ...defaults(), stop: 'Alt+Shift+M' }
    expect(clashes(bindings)).toEqual(['stop'])
    expect(clashes(defaults())).toEqual([])
    expect(clashes({ ...defaults(), summon: '', stop: '' })).toEqual([])
  })

  it('refuses an edit rather than storing something unusable', () => {
    const bindings = defaults()
    expect(withBinding(bindings, 'stop', 'ctrl+alt+p').bindings.stop).toBe('Control+Alt+P')
    expect(withBinding(bindings, 'stop', 'P').error).toContain('modifier')
    expect(withBinding(bindings, 'stop', 'P').bindings).toBe(bindings) // unchanged
    expect(withBinding(bindings, 'stop', 'Alt+Shift+M').error).toContain('summon')
    expect(withBinding(bindings, 'stop', '  ').bindings.stop).toBe('') // cleared
  })
})

describe('on disk', () => {
  it('writes and reads back the same bindings', () => {
    const directory = mkdtempSync(join(tmpdir(), 'marvi-hotkeys-'))
    const bindings = { ...defaults(), stop: 'Control+Alt+P', chat: '' }
    save(directory, bindings)

    expect(JSON.parse(readFileSync(hotkeysPath(directory), 'utf8')).stop).toBe('Control+Alt+P')
    expect(load(directory)).toEqual(bindings)
  })

  it('falls back to defaults when the file is missing or corrupt', () => {
    const directory = mkdtempSync(join(tmpdir(), 'marvi-hotkeys-'))
    expect(load(directory)).toEqual(defaults())

    writeFileSync(hotkeysPath(directory), '{ this is not json', 'utf8')
    expect(load(directory)).toEqual(defaults())
  })
})
