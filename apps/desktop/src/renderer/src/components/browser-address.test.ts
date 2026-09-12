import { describe, expect, it } from 'vitest'
import { START_PAGE, toAddress } from './browser-page'

describe('the address bar', () => {
  it('turns what people type into somewhere the browser can go', () => {
    expect(toAddress('google.com')).toBe('https://google.com')
    expect(toAddress('github.com/marvi')).toBe('https://github.com/marvi')
    expect(toAddress('https://example.org/a')).toBe('https://example.org/a')
    expect(toAddress('weather in duzce')).toBe(
      'https://www.google.com/search?q=weather%20in%20duzce'
    )
  })

  it('never opens a blank page for an empty address', () => {
    expect(toAddress('   ')).toBe(START_PAGE)
  })
})
