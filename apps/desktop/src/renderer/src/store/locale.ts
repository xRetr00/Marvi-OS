import arabicCatalogue from '../locales/ar.json'
import { atom } from 'nanostores'
import { useStore } from '@nanostores/react'
import { persistString, storedString } from '../lib/storage'

export type InterfaceLocale = 'en' | 'ar'
export type InterfaceDirectionPreference = 'follow' | 'ltr' | 'rtl'
const LOCALE_KEY = 'marvi.desktop.interface.locale.v1'
const DIRECTION_KEY = 'marvi.desktop.interface.direction.v1'

export const $interfaceLocale = atom<InterfaceLocale>(
  typeof window !== 'undefined' && storedString(LOCALE_KEY) === 'ar' ? 'ar' : 'en'
)
const storedDirection = typeof window !== 'undefined' ? storedString(DIRECTION_KEY) : null
export const $interfaceDirection = atom<InterfaceDirectionPreference>(
  storedDirection === 'ltr' || storedDirection === 'rtl' ? storedDirection : 'follow'
)

export function setInterfaceLocale(locale: InterfaceLocale): void {
  $interfaceLocale.set(locale)
}

export function setInterfaceDirection(direction: InterfaceDirectionPreference): void {
  $interfaceDirection.set(direction)
}

export function syncLocaleStorage(key: string, value: string | null): boolean {
  if (key === LOCALE_KEY && (value === 'en' || value === 'ar')) {
    $interfaceLocale.set(value)
    return true
  }
  if (key === DIRECTION_KEY && (value === 'follow' || value === 'ltr' || value === 'rtl')) {
    $interfaceDirection.set(value)
    return true
  }
  return false
}

export function resolvedInterfaceDirection(
  locale: InterfaceLocale,
  preference: InterfaceDirectionPreference
): 'ltr' | 'rtl' {
  return preference === 'follow' ? (locale === 'ar' ? 'rtl' : 'ltr') : preference
}

export function applyInterfaceLocale(
  root: HTMLElement,
  locale: InterfaceLocale,
  direction = $interfaceDirection.get()
): void {
  root.lang = locale
  root.dir = resolvedInterfaceDirection(locale, direction)
  root.dataset.locale = locale
  root.dataset.directionPreference = direction
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

export function formatDecimal(
  value: number,
  fractionDigits: number,
  locale = $interfaceLocale.get()
): string {
  return new Intl.NumberFormat(locale === 'ar' ? 'ar-EG' : 'en-US', {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits
  }).format(value)
}

export function formatCurrency(
  value: number,
  currency = 'USD',
  locale = $interfaceLocale.get()
): string {
  return new Intl.NumberFormat(locale === 'ar' ? 'ar-EG' : 'en-US', {
    style: 'currency',
    currency
  }).format(value)
}

export function interpolate(
  message: string,
  values: Record<string, string | number>,
  locale = $interfaceLocale.get()
): string {
  return t(message, locale).replace(/\{([a-zA-Z]+)\}/g, (match, key: string) => {
    const value = values[key]
    return value === undefined ? match : typeof value === 'number' ? formatNumber(value, locale) : value
  })
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
    applyInterfaceLocale(document.documentElement, locale, $interfaceDirection.get())
    persistString(LOCALE_KEY, locale)
  })
  $interfaceDirection.subscribe((direction) => {
    applyInterfaceLocale(document.documentElement, $interfaceLocale.get(), direction)
    persistString(DIRECTION_KEY, direction)
  })
  window.addEventListener('storage', (event) => syncLocaleStorage(event.key ?? '', event.newValue))
}
