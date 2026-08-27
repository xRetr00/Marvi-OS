import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
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

  it('prefers the packaged source and launches its bundled Python directly', async () => {
    const runtime = await import('./messaging-runtime')
    const checkout = join(root, 'checkout')
    const resources = join(root, 'resources')
    const source = join(resources, 'messaging', 'runtime', 'marvi_messaging', 'engine')
    const runtimeRoot = join(resources, 'messaging', 'runtime')
    const python = join(resources, 'messaging', 'python', 'python.exe')
    mkdirSync(
      join(checkout, 'services', 'messaging', 'marvi_messaging', 'engine'),
      { recursive: true }
    )
    mkdirSync(join(source, 'gateway'), { recursive: true })
    mkdirSync(join(runtimeRoot, 'marvi_messaging'), { recursive: true })
    mkdirSync(join(resources, 'messaging', 'python'), { recursive: true })
    writeFileSync(join(source, 'gateway', 'run.py'), '')
    writeFileSync(join(runtimeRoot, 'marvi_messaging', 'main.py'), '')
    writeFileSync(python, '')

    expect(runtime.messagingSourceRoot(checkout, resources)).toBe(source)
    expect(runtime.messagingLaunch(source)).toEqual({
      command: python,
      args: ['-m', 'marvi_messaging.main'],
      cwd: runtimeRoot,
      env: {
        PYTHONPATH: [runtimeRoot, source].join(process.platform === 'win32' ? ';' : ':'),
        MARVI_MESSAGING_ENGINE_ROOT: source
      }
    })
  })

  it('uses a separate messaging home and declares Electron as supervisor', async () => {
    const runtime = await import('./messaging-runtime')
    expect(runtime.messagingEnvironment('C:\\private', 42)).toMatchObject({
      MARVI_MESSAGING_HOME: 'C:\\private',
      MARVI_MESSAGING_PARENT_PID: '42',
      MARVI_MESSAGING_EXTERNAL_SUPERVISOR: '1'
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

  it('tracks the engine as ordinary Marvi files with no nested repository', async () => {
    const runtime = await import('./messaging-runtime')
    const source = join(
      process.cwd(),
      '..',
      '..',
      'services',
      'messaging',
      'marvi_messaging',
      'engine'
    )
    if (!existsSync(join(source, 'gateway', 'run.py'))) return

    expect(existsSync(join(source, '.git'))).toBe(false)
    expect(existsSync(join(source, '..', '..', '.gitmodules'))).toBe(false)
    expect(runtime.messagingPlatforms(source).length).toBeGreaterThanOrEqual(20)
  })

  it('keeps predecessor CLI dispatch out of Marvi runtime ownership', async () => {
    const runtimeMain = join(
      process.cwd(),
      '..',
      '..',
      'services',
      'messaging',
      'marvi_messaging',
      'main.py'
    )
    const electronMain = join(process.cwd(), 'src', 'main', 'messaging-runtime.ts')
    if (!existsSync(runtimeMain)) return

    expect(readFileSync(runtimeMain, 'utf8')).not.toMatch(/legacy[_-]cli/i)
    expect(readFileSync(electronMain, 'utf8')).not.toMatch(/legacy[_-]cli/i)
  })

  it('contains no repository or package-manager operation in the launch boundary', () => {
    const electronMain = join(process.cwd(), 'src', 'main', 'messaging-runtime.ts')
    const source = readFileSync(electronMain, 'utf8')

    expect(source).not.toMatch(/git\s+(clone|pull|fetch)/i)
    expect(source).not.toMatch(/\b(?:uv|pip|npm)\s+(?:run|sync|install)\b/i)
    expect(source).not.toContain('github.com')
  })
})
