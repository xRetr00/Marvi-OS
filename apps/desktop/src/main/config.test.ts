import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { livekitCredentials, logsDir, stateDir } from './config'

let home: string
let saved: Record<string, string | undefined>

beforeEach(() => {
  home = mkdtempSync(join(tmpdir(), 'marvi-config-'))
  saved = {
    MARVI_HOME: process.env['MARVI_HOME'],
    MARVI_LOG_DIR: process.env['MARVI_LOG_DIR'],
    LIVEKIT_API_KEY: process.env['LIVEKIT_API_KEY'],
    LIVEKIT_API_SECRET: process.env['LIVEKIT_API_SECRET']
  }
  process.env['MARVI_HOME'] = home
  delete process.env['MARVI_LOG_DIR']
  delete process.env['LIVEKIT_API_KEY']
  delete process.env['LIVEKIT_API_SECRET']
})

afterEach(() => {
  for (const [key, value] of Object.entries(saved)) {
    if (value === undefined) delete process.env[key]
    else process.env[key] = value
  }
  rmSync(home, { recursive: true, force: true })
})

describe('state layout', () => {
  it('puts the logs under the one state directory', () => {
    // The regression: this file hardcoded 'Marvi OS' with a space while
    // everything else used 'Marvi-OS', so a running Marvi wrote its logs into
    // two directories and neither had the whole story.
    expect(logsDir()).toBe(join(stateDir(), 'logs'))
    expect(stateDir()).toBe(home)
  })
})

describe('livekit credentials', () => {
  it('generates a strong pair and reuses it', () => {
    const first = livekitCredentials()

    expect(first.key).not.toBe('devkey')
    expect(first.secret).not.toBe('secret')
    // The JWT library warns below 32 bytes for SHA256, and it was right to.
    expect(first.secret.length).toBeGreaterThanOrEqual(32)
    expect(existsSync(join(home, 'livekit-keys.json'))).toBe(true)

    // Reused, or the server and the agent would disagree on the next launch.
    expect(livekitCredentials()).toEqual(first)
  })

  it('replaces a stored pair that is too weak to sign with', () => {
    writeFileSync(
      join(home, 'livekit-keys.json'),
      JSON.stringify({ key: 'devkey', secret: 'secret' })
    )

    const credentials = livekitCredentials()

    expect(credentials.secret).not.toBe('secret')
    expect(credentials.secret.length).toBeGreaterThanOrEqual(32)
    const stored = JSON.parse(readFileSync(join(home, 'livekit-keys.json'), 'utf8'))
    expect(stored.secret).toBe(credentials.secret)
  })

  it('lets the environment win, for a cloud LiveKit project', () => {
    process.env['LIVEKIT_API_KEY'] = 'API7xyz'
    process.env['LIVEKIT_API_SECRET'] = 'a'.repeat(40)

    expect(livekitCredentials()).toEqual({ key: 'API7xyz', secret: 'a'.repeat(40) })
    expect(existsSync(join(home, 'livekit-keys.json'))).toBe(false)
  })
})
