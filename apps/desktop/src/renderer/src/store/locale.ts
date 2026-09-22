import arabicCatalogue from '../locales/ar.json'
import { atom } from 'nanostores'
import { useStore } from '@nanostores/react'
import { persistString, storedString } from '../lib/storage'

export type InterfaceLocale = 'en' | 'ar'
const LOCALE_KEY = 'marvi.desktop.interface.locale.v1'

export const $interfaceLocale = atom<InterfaceLocale>(
  typeof window !== 'undefined' && storedString(LOCALE_KEY) === 'ar' ? 'ar' : 'en'
)

export function setInterfaceLocale(locale: InterfaceLocale): void {
  $interfaceLocale.set(locale)
}

export function syncLocaleStorage(key: string, value: string | null): boolean {
  if (key !== LOCALE_KEY || (value !== 'en' && value !== 'ar')) return false
  $interfaceLocale.set(value)
  return true
}

export function applyInterfaceLocale(root: HTMLElement, locale: InterfaceLocale): void {
  root.lang = locale
  root.dir = locale === 'ar' ? 'rtl' : 'ltr'
  root.dataset.locale = locale
}

// English is the lookup key and the visible fallback while the catalogue grows.
export const arabic: Record<string, string> = arabicCatalogue

export function t(message: string, locale = $interfaceLocale.get()): string {
  return locale === 'ar' ? (arabic[message] ?? message) : message
}

/** Reactive text for literal JSX labels, including in the separate Island renderer. */
export function Tr({
  text,
  before = false,
  after = false
}: {
  text: string
  before?: boolean
  after?: boolean
}): string {
  const locale = useStore($interfaceLocale)
  return `${before ? ' ' : ''}${t(text, locale)}${after ? ' ' : ''}`
}

export function formatNumber(value: number, locale = $interfaceLocale.get()): string {
  return new Intl.NumberFormat(locale === 'ar' ? 'ar-EG' : 'en-US').format(value)
}

export function formatDate(
  value: Date | number,
  options: Intl.DateTimeFormatOptions,
  locale = $interfaceLocale.get()
): string {
  return new Intl.DateTimeFormat(locale === 'ar' ? 'ar-EG' : 'en-US', options).format(value)
}

export function formatRelative(
  value: number,
  unit: Intl.RelativeTimeFormatUnit,
  locale = $interfaceLocale.get()
): string {
  return new Intl.RelativeTimeFormat(locale === 'ar' ? 'ar-EG' : 'en-US', {
    numeric: 'auto'
  }).format(value, unit)
}

if (typeof document !== 'undefined') {
  $interfaceLocale.subscribe((locale) => {
    applyInterfaceLocale(document.documentElement, locale)
    persistString(LOCALE_KEY, locale)
  })
  window.addEventListener('storage', (event) => syncLocaleStorage(event.key ?? '', event.newValue))
}
