import { type ChildProcess, spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join } from 'node:path'

import { stateDir } from './config'
import { log as writeLog } from './logger'
import { groupSpawnOptions, isAlive, killStrays, killTree, stopTree, whoHasPort } from './processes'

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

/**
 * Services write to stdout and stderr interchangeably - uvicorn logs INFO to
 * stderr - so the stream is a poor signal. Reading the line is a better one.
 */
export function looksLikeError(line: string): boolean {
  // A child that writes its own structured logs has already said what level a
  // line is, and re-deciding from keywords gets it wrong: the Gateway's
  // `INFO [retry] room.get_state failed, retrying in 0.1s` was landing in
  // errors.log as an ERROR, once per retry, because it contains "failed".
  //
  // So a declared level is believed, and only an unlabelled line falls back to
  // the keyword guess.
  const declared = /\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b/.exec(line)
  if (declared) return declared[1] === 'ERROR' || declared[1] === 'CRITICAL'
  return /\b(error|traceback|exception|critical|failed|fatal)\b/i.test(line)
}

/**
 * Has the child already written this line to Marvi's log files itself?
 *
 * The Gateway and the agent log into the same directory, so capturing their
 * stdout and writing it again duplicates every line — once structured, once
 * wrapped in `ERROR [gateway] desktop —`. The in-memory tail still keeps
 * everything, because a crashed service's last words are what the Doctor page
 * is for.
 */
export function alreadyLogged(line: string): boolean {
  return /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b/.test(
    line
  )
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
  /** Where this installation lives, so another checkout is left alone. */
  installRoot?: string
  /**
   * The port this service listens on, if it does.
   *
   * Only used to explain a failure: "address already in use" is the one exit
   * whose cause is somewhere else entirely, and naming the process that has
   * the port is the difference between a fixable message and a restart loop.
   */
  port?: number
  /**
   * How to recognise this service among running processes, for sweeping a
   * previous copy before starting a new one. Without it a restart leaves the
   * old process running and they accumulate.
   */
  match?: RegExp
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
      // Also to disk, unless the child already wrote it there itself. The
      // in-memory tail serves the Doctor page; the file is what survives a
      // restart and what someone can actually send.
      if (!alreadyLogged(text)) {
        writeLog(this.spec.name, looksLikeError(text) ? 'ERROR' : 'INFO', text)
      }
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

    // Anything of this service still running from before. A restart that
    // leaves the old one alive gets two, and a crash-restart loop gets more:
    // five agent workers ended up registered against one LiveKit server, and a
    // job dispatched to a stale one never ran, so voice sat on READY forever.
    //
    // Killing the tree we know about is not enough -- `uv` launches Python as
    // a grandchild and a killed parent can leave it -- so this sweeps by name.
    //
    // Only for a service that said how to recognise itself. Without a pattern
    // this fell back to scanning every process on the machine, which is a WMI
    // query costing seconds -- paid on every start, to find leftovers of a
    // service it could not identify anyway. It timed out the supervisor's own
    // test on a slow runner, which is a fair warning about what it was doing
    // on somebody's desktop.
    if (this.spec.match) {
      const leftover = killStrays(this.spec.installRoot, this.spec.match)
      if (leftover > 0) {
        this.log(`stopped ${leftover} leftover process(es) before starting`)
      }
    }

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
        env: { ...process.env, ...this.spec.env },
        // Its own process group, so the whole tree can be signalled at once.
        // Every service here is `uv` launching Python, so the process that
        // matters is a grandchild.
        ...groupSpawnOptions()
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
    this.detail = this.explainPort(detail)
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

  /**
   * Turn "address already in use" into who has it.
   *
   * The Gateway wrote `[Errno 10048] only one usage of each socket address`
   * and exited, the supervisor restarted it, and it failed the same way every
   * ten seconds for an hour without once saying what was already there. It was
   * a Gateway from a second checkout, running since the previous evening --
   * invisible from here, because `killStrays` is scoped to this install root
   * and correctly leaves another checkout's processes alone.
   *
   * So this names it rather than killing it: another checkout's Gateway may be
   * something somebody is using, and the person reading this is the one who
   * knows.
   */
  private explainPort(detail: string): string {
    if (!/10048|EADDRINUSE|address already in use/i.test(`${detail} ${this.output.join(' ')}`)) {
      return detail
    }
    const port = this.spec.port
    if (!port) return detail
    const holder = whoHasPort(port)
    if (!holder) return `port ${port} is already in use, and nothing is listening on it now`
    return (
      `port ${port} is already taken by process ${holder.pid}` +
      (holder.command ? ` (${holder.command})` : '') +
      '. Close that, or change this one’s port.'
    )
  }

  /**
   * Stop this service and everything it started.
   *
   * `child.kill()` would end `uv` and leave the Python it spawned running,
   * holding the port and the checkout. That orphan then breaks the next update
   * and fights the next launch for 8765.
   */
  stop(): void {
    this.stopping = true
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
    const child = this.child
    this.child = null
    if (!child) return
    void stopTree(child).catch(() => killTree(child.pid, true))
  }

  /** Synchronous, for `will-quit` where a promise will not be awaited. */
  stopNow(): void {
    this.stopping = true
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
    const pid = this.child?.pid
    this.child = null
    if (pid) killTree(pid, true)
  }

  alive(): boolean {
    return isAlive(this.child?.pid)
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

  /** Immediate, for quit: Electron will not wait for a promise there. */
  stopAllNow(): void {
    for (const service of this.services.values()) service.stopNow()
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
    // Marvi's own copy first. The installer provisions it precisely so there
    // is a path that does not depend on whose PATH this process inherited.
    join(stateDir(), 'toolchain', 'uv', 'uv.exe'),
    join(stateDir(), 'toolchain', 'uv', 'uv'),
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
