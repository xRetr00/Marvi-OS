import { afterEach, describe, expect, it } from 'vitest'

import { gatewayCopy } from './gateway-copy'
import { setInterfaceLocale } from './locale'

afterEach(() => setInterfaceLocale('en'))

describe('Gateway display copy', () => {
  it('preserves English status prose', () => {
    expect(gatewayCopy('local server online')).toBe('local server online')
    expect(gatewayCopy('2 connected, 1 need reconnect')).toBe('2 connected, 1 need reconnect')
  })

  it('localizes known prose and interpolated counts at the renderer boundary', () => {
    setInterfaceLocale('ar')
    expect(gatewayCopy('local server online')).toBe('الخادم المحلي متصل')
    expect(gatewayCopy('2 connected, 1 need reconnect')).toContain('٢')
    expect(gatewayCopy('Smart Room camera online, 3 visible, Shereef')).toContain('٣')
  })

  it('keeps unknown diagnostic detail visible as an English fallback', () => {
    setInterfaceLocale('ar')
    expect(gatewayCopy('driver refused 127.0.0.1')).toBe('driver refused 127.0.0.1')
  })
})
