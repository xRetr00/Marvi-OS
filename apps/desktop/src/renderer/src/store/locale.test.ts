import { afterEach, describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { createElement } from 'react'
import {
  applyInterfaceLocale,
  resolvedInterfaceDirection,
  formatDate,
  formatDecimal,
  formatNumber,
  formatRelative,
  interpolate,
  setInterfaceLocale,
  setInterfaceDirection,
  Tr,
  syncLocaleStorage,
  t
} from './locale'

afterEach(() => {
  setInterfaceDirection('follow')
  setInterfaceLocale('en')
})

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

  it('lets layout direction follow language or override it independently', () => {
    expect(resolvedInterfaceDirection('ar', 'follow')).toBe('rtl')
    expect(resolvedInterfaceDirection('ar', 'ltr')).toBe('ltr')
    expect(resolvedInterfaceDirection('en', 'rtl')).toBe('rtl')
    const root = { lang: '', dir: '', dataset: {} } as unknown as HTMLElement
    applyInterfaceLocale(root, 'ar', 'ltr')
    expect(root.lang).toBe('ar')
    expect(root.dir).toBe('ltr')
    expect(root.dataset.directionPreference).toBe('ltr')
  })

  it('accepts only persisted interface locales and falls back to English', () => {
    expect(syncLocaleStorage('wrong', 'ar')).toBe(false)
    expect(syncLocaleStorage('marvi.desktop.interface.locale.v1', 'fr')).toBe(false)
    expect(syncLocaleStorage('marvi.desktop.interface.locale.v1', 'ar')).toBe(true)
    expect(syncLocaleStorage('marvi.desktop.interface.direction.v1', 'ltr')).toBe(true)
    expect(t('Chat')).toBe('الدردشة')
    expect(t('untranslated')).toBe('untranslated')
  })

  it('formats Arabic numbers, dates, and relative times through Intl', () => {
    expect(formatNumber(1234, 'ar')).toContain('١')
    expect(formatDate(new Date('2026-09-22T12:00:00Z'), { year: 'numeric' }, 'ar')).toContain(
      '٢٠٢٦'
    )
    expect(formatRelative(-2, 'day', 'ar')).toBe('أول أمس')
    expect(formatDecimal(1.5, 1, 'ar')).toContain('١')
    expect(interpolate('{count} learned', { count: 12 }, 'ar')).toBe('تعلّم ١٢')
  })

  it('renders extracted labels in Arabic while preserving inline spacing', () => {
    setInterfaceLocale('ar')
    expect(renderToStaticMarkup(createElement(Tr, { text: 'Save', before: true, after: true })))
      .toBe(' حفظ ')
  })
})
