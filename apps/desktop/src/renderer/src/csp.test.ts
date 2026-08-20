import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * The renderer's Content-Security-Policy.
 *
 * One line of HTML that silently breaks all of voice. The policy had no
 * `connect-src`, so it fell back to `default-src 'self'` and the page could
 * not reach the LiveKit server at all — every Join failed before leaving the
 * renderer, and the SDK reported it as
 *
 *     ConnectionError: could not establish signal connection: Failed to fetch
 *
 * which reads like the server was down. It was answering the whole time.
 *
 * Asserted rather than trusted, because nothing else in the app fails when
 * this is wrong: the tests pass, the build passes, and only a real Join tells
 * you.
 */
const policy = (() => {
  const html = readFileSync(join(__dirname, '..', 'index.html'), 'utf8')
  const match = html.match(/http-equiv="Content-Security-Policy"[\s\S]*?content="([^"]+)"/)
  if (!match) throw new Error('no Content-Security-Policy in index.html')
  return match[1]
})()

function directive(name: string): string[] {
  const found = policy
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${name} `))
  return found ? found.split(/\s+/).slice(1) : []
}

describe('the renderer content security policy', () => {
  it('lets the page reach LiveKit over loopback', () => {
    const sources = directive('connect-src')

    expect(sources).toContain('ws://127.0.0.1:*')
    expect(sources).toContain('http://127.0.0.1:*')
  })

  it('does not fall back to default-src for connections', () => {
    // The actual bug: the directive was absent entirely.
    expect(directive('connect-src').length).toBeGreaterThan(0)
  })

  it('reaches nothing beyond this machine', () => {
    // Loopback only. A wildcard host here would make the policy decorative,
    // and this page holds the user's provider credentials in memory.
    for (const source of directive('connect-src')) {
      expect(source === "'self'" || /^(https?|wss?):\/\/(127\.0\.0\.1|localhost):/.test(source)).toBe(
        true
      )
    }
  })

  it('still refuses remote scripts', () => {
    expect(directive('script-src')).toEqual(["'self'"])
  })
})
