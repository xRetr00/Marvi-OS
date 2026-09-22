import { afterEach, describe, expect, it } from 'vitest'
import {
  applyInterfaceLocale,
  formatDate,
  formatNumber,
  formatRelative,
  setInterfaceLocale,
  syncLocaleStorage,
  t
} from './locale'

afterEach(() => setInterfaceLocale('en'))

describe('interface locale', () => {
  it('changes document language and direction', () => {
    const root = { lang: '', dir: '', dataset: {} } as unknown as HTMLElement
    applyInterfaceLocale(root, 'ar')
    expect(root.lang).toBe('ar')
    expect(root.dir).toBe('rtl')
    expect(root.dataset.locale).toBe('ar')
    applyInterfaceLocale(root, 'en')
    expect(root.dir).toBe('ltr')
  })

  it('accepts only persisted interface locales and falls back to English', () => {
    expect(syncLocaleStorage('wrong', 'ar')).toBe(false)
    expect(syncLocaleStorage('marvi.desktop.interface.locale.v1', 'fr')).toBe(false)
    expect(syncLocaleStorage('marvi.desktop.interface.locale.v1', 'ar')).toBe(true)
    expect(t('Chat')).toBe('الدردشة')
    expect(t('untranslated')).toBe('untranslated')
  })

  it('formats Arabic numbers, dates, and relative times through Intl', () => {
    expect(formatNumber(1234, 'ar')).toContain('١')
    expect(formatDate(new Date('2026-09-22T12:00:00Z'), { year: 'numeric' }, 'ar')).toContain(
      '٢٠٢٦'
    )
    expect(formatRelative(-2, 'day', 'ar')).toBe('أول أمس')
  })
})
