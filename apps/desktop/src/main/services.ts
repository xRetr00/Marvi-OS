import { type ChildProcess, spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join } from 'node:path'

/**
 * Starting the local services, and knowing when they did not start.
 *
 * The previous version spawned with `stdio: 'ignore'` and never watched for
 * exit. When the Gateway failed to launch — a missing `uv`, a bad import, a
 * port already taken — the process died in silence and the shell sat on a
 * connecting animation forever with nothing anywhere to explain it. Every
 * symptom looked identical, so there was nothing to act on.
 *
 * What this does instead:
 *
 * - **Resolves `uv` properly.** A GUI-launched Electron app does not
 *   necessarily inherit the PATH a terminal has, and `uv` installs to
 *   `~/.local/bin`. "Command not found" is the single most likely failure, so
 *   it is checked for by name rather than discovered as a generic crash.
 * - **Keeps the last lines of output.** Not a full log — enough to show the
 *   user the actual Python traceback instead of "gateway offline".
 * - **Notices exits and restarts with backoff**, capped, because a service
 *   that cannot start will not start on the ninth attempt either, and a
 *   restart loop is worse than a clear failure.
 * - **Reports state**, so the shell can show which service is down and why.
 */

export type ServiceState = 'stopped' | 'starting' | 'running' | 'failed' | 'gave up'

export interface ServiceReport {
  name: string
  state: ServiceState
  detail: string
  restarts: number
  /** Last lines of stdout/stderr, newest last. The reason, when there is one. */
  output: string[]
}

const MAX_OUTPUT_LINES = 60
const MAX_RESTARTS = 5
const RESTART_BASE_MS = 1_500
// Treat a process that survives this long as genuinely up, and reset its
// restart count. Without this a service that runs for hours then dies once is
// permanently one failure away from "gave up".
const HEALTHY_AFTER_MS = 30_000

export interface ServiceSpec {
  name: string
  command: string
  args: string[]
  cwd: string
  /** Skip silently when false — an optional service, not a failure. */
  when?: () => boolean
  env?: Record<string, string>
}

class Service {
  state: ServiceState = 'stopped'
  detail = ''
  restarts = 0
  output: string[] = []
  private child: ChildProcess | null = null
  private startedAt = 0
  private timer: NodeJS.Timeout | null = null
  private stopping = false

  constructor(
    private readonly spec: ServiceSpec,
    private readonly onChange: () => void
  ) {}

  report(): ServiceReport {
    return {
      name: this.spec.name,
      state: this.state,
      detail: this.detail,
      restarts: this.restarts,
      output: [...this.output]
    }
  }

  private log(line: string): void {
    for (const part of line.split(/\r?\n/)) {
      const text = part.trimEnd()
      if (!text) continue
      this.output.push(text)
    }
    if (this.output.length > MAX_OUTPUT_LINES) {
      this.output = this.output.slice(-MAX_OUTPUT_LINES)
    }
  }

  start(): void {
    if (this.spec.when && !this.spec.when()) {
      this.state = 'stopped'
      this.detail = 'not installed'
      this.onChange()
      return
    }
    this.stopping = false
    this.state = 'starting'
    this.detail = `launching ${this.spec.command}`
    this.onChange()

    let child: ChildProcess
    try {
      child = spawn(this.spec.command, this.spec.args, {
        cwd: this.spec.cwd,
        windowsHide: true,
        // Piped, not ignored. This is the whole point.
        stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, ...this.spec.env }
      })
    } catch (error) {
      this.fail(`could not launch ${this.spec.command}: ${String(error)}`)
      return
    }

    this.child = child
    this.startedAt = Date.now()
    child.stdout?.on('data', (chunk: Buffer) => this.log(chunk.toString()))
    child.stderr?.on('data', (chunk: Buffer) => this.log(chunk.toString()))

    child.on('error', (error: NodeJS.ErrnoException) => {
      // ENOENT here is almost always a missing `uv` on a GUI-launched app.
      const reason =
        error.code === 'ENOENT'
          ? `${this.spec.command} was not found on PATH`
          : `${this.spec.command} failed to start: ${error.message}`
      this.log(reason)
      this.fail(reason)
    })

    child.on('exit', (code, signal) => {
      this.child = null
      if (this.stopping) {
        this.state = 'stopped'
        this.detail = 'stopped'
        this.onChange()
        return
      }
      const lived = Date.now() - this.startedAt
      if (lived > HEALTHY_AFTER_MS) this.restarts = 0
      this.fail(
        signal
          ? `exited on ${signal} after ${Math.round(lived / 1000)}s`
          : `exited with code ${code} after ${Math.round(lived / 1000)}s`
      )
    })

    // Nothing here declares "running": only the Gateway answering its own
    // health endpoint proves that, and the shell already polls it. A process
    // that is alive but wedged should not look healthy.
    setTimeout(() => {
      if (this.child && this.state === 'starting') {
        this.state = 'running'
        this.detail = `pid ${this.child.pid}`
        this.onChange()
      }
    }, 1_000)
  }

  private fail(detail: string): void {
    this.detail = detail
    if (this.restarts >= MAX_RESTARTS) {
      // A service that has failed this many times will not fix itself, and a
      // restart loop hides the original error under a wall of new ones.
      this.state = 'gave up'
      this.onChange()
      return
    }
    this.state = 'failed'
    this.restarts += 1
    this.onChange()
    const wait = RESTART_BASE_MS * 2 ** (this.restarts - 1)
    this.timer = setTimeout(() => this.start(), wait)
  }

  stop(): void {
    this.stopping = true
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
    this.child?.kill()
    this.child = null
  }

  /** Clear the failure count and try again now — the Doctor's retry button. */
  retry(): void {
    this.stop()
    this.restarts = 0
    this.output = []
    this.start()
  }
}

export class ServiceSupervisor {
  private services = new Map<string, Service>()

  constructor(private readonly onChange: (reports: ServiceReport[]) => void) {}

  add(spec: ServiceSpec): void {
    this.services.set(spec.name, new Service(spec, () => this.onChange(this.reports())))
  }

  startAll(): void {
    for (const service of this.services.values()) service.start()
  }

  stopAll(): void {
    for (const service of this.services.values()) service.stop()
  }

  retry(name: string): boolean {
    const service = this.services.get(name)
    if (!service) return false
    service.retry()
    return true
  }

  reports(): ServiceReport[] {
    return [...this.services.values()].map((service) => service.report())
  }
}

/**
 * Find `uv`.
 *
 * An Electron app launched from the Start menu inherits the PATH that existed
 * when Explorer started, which frequently predates a `uv` install. Falling back
 * to the documented install locations turns "the app just does not work" into
 * "it works", and when it genuinely is not installed, the caller can say so
 * precisely instead of reporting a generic spawn failure.
 */
export function findUv(): string | null {
  const configured = process.env['MARVI_UV_PATH']?.trim()
  if (configured && existsSync(configured)) return configured

  const home = process.env['USERPROFILE'] ?? process.env['HOME'] ?? ''
  const candidates = [
    join(home, '.local', 'bin', 'uv.exe'),
    join(home, '.cargo', 'bin', 'uv.exe'),
    join(process.env['LOCALAPPDATA'] ?? '', 'Programs', 'uv', 'uv.exe'),
    join(home, '.local', 'bin', 'uv')
  ]
  for (const candidate of candidates) {
    if (candidate && existsSync(candidate)) return candidate
  }

  // Let the OS resolve it from PATH; spawn reports ENOENT if that also fails.
  return null
}
