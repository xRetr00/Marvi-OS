import { mkdtempSync, writeFileSync, mkdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { gatewayBind, gatewayUrl, livekitServerPath, manifest } from './config'
import { ServiceSupervisor, findUv, type ServiceReport } from './services'

/**
 * These cover the two things that made the app look broken with no explanation:
 * a service dying into a `stdio: 'ignore'` pipe, and `uv` not being on the PATH
 * a GUI-launched Electron inherits.
 */

let root: string

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'marvi-cfg-'))
  vi.resetModules()
})

afterEach(() => {
  rmSync(root, { recursive: true, force: true })
  delete process.env['MARVI_GATEWAY_URL']
  delete process.env['MARVI_UV_PATH']
  delete process.env['MARVI_LIVEKIT_SERVER']
})

function writeManifest(gatewayPort: number, livekitVersion: string): void {
  mkdirSync(join(root, 'config'), { recursive: true })
  writeFileSync(
    join(root, 'config', 'runtime.json'),
    JSON.stringify({
      gateway: { host: '127.0.0.1', port: gatewayPort },
      livekit: { version: livekitVersion, host: '127.0.0.1', port: 7880 }
    })
  )
}

describe('runtime configuration', () => {
  it('reads the port from the manifest rather than a literal', async () => {
    writeManifest(9100, '1.13.5')
    const config = await import('./config')

    expect(config.gatewayUrl(root)).toBe('http://127.0.0.1:9100')
  })

  it('binds the server to the same place the shell will poll', async () => {
    writeManifest(9100, '1.13.5')
    const config = await import('./config')

    // Two copies of a port is the bug this replaced: the shell polled 8765
    // while the server could have been told to listen anywhere.
    const bind = config.gatewayBind(root)
    expect(config.gatewayUrl(root)).toBe(`http://${bind.host}:${bind.port}`)
  })

  it('lets the environment override the manifest', async () => {
    writeManifest(9100, '1.13.5')
    process.env['MARVI_GATEWAY_URL'] = 'http://127.0.0.1:9999/'
    const config = await import('./config')

    expect(config.gatewayUrl(root)).toBe('http://127.0.0.1:9999')
    expect(config.gatewayBind(root).port).toBe('9999')
  })

  it('takes the LiveKit version from the manifest, not from three files', async () => {
    writeManifest(8765, '9.9.9')
    const config = await import('./config')

    expect(config.livekitServerPath(root)).toContain('9.9.9')
  })

  it('still starts when the manifest is missing', () => {
    // A broken install must produce a running app that can explain itself,
    // not a crash on the first line of startup.
    expect(() => manifest(join(root, 'nowhere'))).not.toThrow()
    expect(gatewayUrl(join(root, 'nowhere'))).toMatch(/^http:\/\//)
    expect(gatewayBind(null).port).toBeTruthy()
    expect(livekitServerPath(null)).toContain('livekit-server.exe')
  })
})

describe('finding uv', () => {
  it('honours an explicit path', () => {
    const fake = join(root, 'uv.exe')
    writeFileSync(fake, '')
    process.env['MARVI_UV_PATH'] = fake

    expect(findUv()).toBe(fake)
  })

  it('ignores a configured path that does not exist', () => {
    process.env['MARVI_UV_PATH'] = join(root, 'missing.exe')

    // Better to fall through to the real search than to spawn something that
    // is not there and report a confusing ENOENT.
    expect(findUv()).not.toBe(process.env['MARVI_UV_PATH'])
  })
})

describe('supervising a service', () => {
  it('captures output instead of discarding it', async () => {
    const seen: ServiceReport[][] = []
    const supervisor = new ServiceSupervisor((reports) => seen.push(reports))
    supervisor.add({
      name: 'noisy',
      command: process.execPath,
      args: ['-e', 'console.log("hello from the service"); process.exit(0)'],
      cwd: root
    })
    supervisor.startAll()

    await vi.waitFor(
      () => {
        const latest = seen.at(-1)?.[0]
        expect(latest?.output.join('\n')).toContain('hello from the service')
      },
      { timeout: 8_000 }
    )
    supervisor.stopAll()
  })

  it('reports why a service exited', async () => {
    const seen: ServiceReport[][] = []
    const supervisor = new ServiceSupervisor((reports) => seen.push(reports))
    supervisor.add({
      name: 'crasher',
      command: process.execPath,
      args: ['-e', 'console.error("Traceback: no module named marvi_gateway"); process.exit(3)'],
      cwd: root
    })
    supervisor.startAll()

    await vi.waitFor(
      () => {
        const latest = seen.at(-1)?.[0]
        // The old behaviour was silence. The reason is the whole point.
        expect(latest?.detail).toContain('code 3')
        expect(latest?.output.join('\n')).toContain('no module named marvi_gateway')
      },
      { timeout: 8_000 }
    )
    supervisor.stopAll()
  })

  it('reports a missing command by name', async () => {
    const seen: ServiceReport[][] = []
    const supervisor = new ServiceSupervisor((reports) => seen.push(reports))
    supervisor.add({
      name: 'absent',
      command: join(root, 'definitely-not-here.exe'),
      args: [],
      cwd: root
    })
    supervisor.startAll()

    await vi.waitFor(
      () => {
        const latest = seen.at(-1)?.[0]
        expect(latest?.detail).toMatch(/not found|failed to start|ENOENT/i)
      },
      { timeout: 8_000 }
    )
    supervisor.stopAll()
  })

  it('skips an optional service without calling it a failure', () => {
    const seen: ServiceReport[][] = []
    const supervisor = new ServiceSupervisor((reports) => seen.push(reports))
    supervisor.add({
      name: 'optional',
      command: 'never-run',
      args: [],
      cwd: root,
      when: () => false
    })
    supervisor.startAll()

    // A cloud LiveKit URL means no local server, which is a configuration, not
    // a fault.
    expect(seen.at(-1)?.[0].state).toBe('stopped')
    expect(seen.at(-1)?.[0].detail).toBe('not installed')
  })

  it('resolves dynamic service settings when the process actually starts', async () => {
    const seen: ServiceReport[][] = []
    let profile = 'second-profile'
    const supervisor = new ServiceSupervisor((reports) => seen.push(reports))
    supervisor.add({
      name: 'dynamic',
      command: process.execPath,
      args: ['-e', 'console.log(process.env.MARVI_TEST_PROFILE)'],
      cwd: root,
      env: () => ({ MARVI_TEST_PROFILE: profile })
    })
    profile = 'selected-at-start'
    supervisor.startAll()

    await vi.waitFor(
      () => {
        expect(seen.at(-1)?.[0].output.join('\n')).toContain('selected-at-start')
      },
      { timeout: 8_000 }
    )
    supervisor.stopAll()
  })

  it('gives up rather than looping forever', async () => {
    const seen: ServiceReport[][] = []
    const supervisor = new ServiceSupervisor((reports) => seen.push(reports))
    supervisor.add({
      name: 'hopeless',
      command: process.execPath,
      args: ['-e', 'process.exit(1)'],
      cwd: root
    })
    supervisor.startAll()

    await vi.waitFor(
      () => {
        // A restart loop buries the original error under a wall of new ones.
        expect(seen.at(-1)?.[0].state).toBe('gave up')
      },
      { timeout: 60_000 }
    )
    supervisor.stopAll()
  }, 70_000)
})

describe('what gets written to the log files', () => {
  it('believes a level the child already declared', async () => {
    const { looksLikeError } = await import('./services')
    // The regression: this line went to errors.log once per retry because it
    // contains the word "failed", while saying INFO on its face.
    expect(
      looksLikeError('2026-08-18 04:26:59,539 INFO    [retry] room.get_state failed, retrying')
    ).toBe(false)
    expect(looksLikeError('2026-08-18 04:26:59,539 ERROR   [gateway] something broke')).toBe(true)
  })

  it('still guesses for a line that declares nothing', async () => {
    const { looksLikeError } = await import('./services')
    expect(looksLikeError('Traceback (most recent call last):')).toBe(true)
    expect(looksLikeError('listening on 127.0.0.1:8765')).toBe(false)
  })

  it('does not write a line the child already logged itself', async () => {
    const { alreadyLogged } = await import('./services')
    // The Gateway logs into the same directory, so capturing its stdout and
    // writing it again put every line in twice.
    expect(alreadyLogged('2026-08-18 04:26:59,539 INFO    [retry] marvi.retry — x')).toBe(true)
    expect(alreadyLogged('npm warn EBADENGINE')).toBe(false)
  })
})

describe('a restart that would leave the old process running', () => {
  /**
   * Five agent workers ended up registered against one LiveKit server. A job
   * dispatched to a stale one never ran, so voice sat on READY forever, and
   * nothing in the UI could show why.
   */
  it('sweeps a previous copy of the service before starting a new one', async () => {
    const swept: Array<[string | undefined, RegExp | undefined]> = []
    vi.doMock('./processes', async () => ({
      ...(await vi.importActual<typeof import('./processes')>('./processes')),
      killStrays: (installRoot?: string, match?: RegExp) => {
        swept.push([installRoot, match])
        return 1
      }
    }))

    const { ServiceSupervisor: Supervisor } = await import('./services')
    const supervisor = new Supervisor(() => {})
    supervisor.add({
      name: 'agent',
      command: process.execPath,
      args: ['-e', 'setTimeout(() => {}, 60000)'],
      cwd: root,
      installRoot: root,
      match: /marvi_agent/i
    })

    supervisor.startAll()
    supervisor.stopAllNow()

    expect(swept).toEqual([[root, /marvi_agent/i]])
  })

  it('does not go looking when the service cannot describe itself', async () => {
    /**
     * Sweeping without a pattern falls back to scanning every process on the
     * machine, which is a WMI query costing seconds -- paid on every start, to
     * find leftovers of a service it could not identify anyway. It timed out
     * this file's own test on a CI runner, which is a fair warning about what
     * it was doing on a desktop.
     */
    const swept: unknown[] = []
    vi.doMock('./processes', async () => ({
      ...(await vi.importActual<typeof import('./processes')>('./processes')),
      killStrays: (...args: unknown[]) => {
        swept.push(args)
        return 0
      }
    }))

    const { ServiceSupervisor: Supervisor } = await import('./services')
    const supervisor = new Supervisor(() => {})
    supervisor.add({
      name: 'anonymous',
      command: process.execPath,
      args: ['-e', 'setTimeout(() => {}, 60000)'],
      cwd: root
    })

    supervisor.startAll()
    supervisor.stopAllNow()

    expect(swept).toEqual([])
  })
})
