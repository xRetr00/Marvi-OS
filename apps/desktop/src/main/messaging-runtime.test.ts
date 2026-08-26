import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

let root: string
let home: string

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'marvi-messaging-'))
  home = join(root, 'state')
  process.env['MARVI_HOME'] = home
  vi.resetModules()
})

afterEach(() => {
  delete process.env['MARVI_HOME']
  delete process.env['MARVI_MESSAGING_HOME']
  rmSync(root, { recursive: true, force: true })
})

describe('messaging runtime', () => {
  it('stays off until the user enables the optional gateway', async () => {
    const runtime = await import('./messaging-runtime')
    expect(runtime.readMessagingPreferences()).toEqual({
      enabled: false,
      home: join(home, 'messaging-agent')
    })
  })

  it('persists only lifecycle preferences, never platform credentials', async () => {
    const runtime = await import('./messaging-runtime')
    const customHome = join(root, 'private-messaging-home')
    runtime.writeMessagingPreferences({ enabled: true, home: customHome })

    expect(runtime.readMessagingPreferences()).toEqual({ enabled: true, home: customHome })
  })

  it('discovers platform values from the pinned engine', async () => {
    const runtime = await import('./messaging-runtime')
    const source = join(root, 'source')
    mkdirSync(join(source, 'gateway'), { recursive: true })
    writeFileSync(
      join(source, 'gateway', 'config.py'),
      `class Platform(Enum):\n    TELEGRAM = "telegram"\n    DISCORD = 'discord'\n`
    )

    expect(runtime.messagingPlatforms(source)).toEqual(['discord', 'telegram'])
  })

  it('uses a separate upstream home and declares Electron as supervisor', async () => {
    const runtime = await import('./messaging-runtime')
    expect(runtime.messagingEnvironment('C:\\private', 42)).toMatchObject({
      HERMES_HOME: 'C:\\private',
      MARVI_PARENT_PID: '42',
      HERMES_GATEWAY_EXTERNAL_SUPERVISOR: '1'
    })
  })

  it('requires installation, configuration, and explicit enablement before launch', async () => {
    const runtime = await import('./messaging-runtime')
    const base = {
      enabled: false,
      configured: false,
      installed: false,
      home: 'C:\\private',
      sourceRoot: 'C:\\source',
      sourceCommit: runtime.MESSAGING_SOURCE_COMMIT,
      platforms: [],
      setupCommand: 'setup'
    }

    expect(runtime.shouldStartMessaging({ ...base, installed: true, configured: true })).toBe(false)
    expect(runtime.shouldStartMessaging({ ...base, configured: true, enabled: true })).toBe(false)
    expect(runtime.shouldStartMessaging({ ...base, installed: true, enabled: true })).toBe(false)
    expect(
      runtime.shouldStartMessaging({
        ...base,
        installed: true,
        configured: true,
        enabled: true
      })
    ).toBe(true)
  })

  it('pins the materialized engine and discovers its complete platform catalogue', async () => {
    const runtime = await import('./messaging-runtime')
    const source = join(process.cwd(), '..', '..', 'vendor', 'marvi-agent')
    if (!existsSync(join(source, 'gateway', 'run.py'))) return

    const head = execFileSync('git', ['-C', source, 'rev-parse', 'HEAD'], {
      encoding: 'utf8',
      windowsHide: true
    }).trim()
    expect(head).toBe(runtime.MESSAGING_SOURCE_COMMIT)
    expect(runtime.messagingPlatforms(source).length).toBeGreaterThanOrEqual(20)
  })
})
