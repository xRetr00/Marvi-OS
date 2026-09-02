/**
 * Who owns the Marvi processes on this machine, written down rather than guessed.
 *
 * The lifecycle used to infer ownership from the operating system: whoever
 * held port 8765 was adopted if its *parent* process still existed and killed
 * if it did not. Every branch of that is wrong in some case — a recycled PID,
 * an old desktop still shutting down, a Gateway started from a shell, a
 * machine that rebooted — and the moment a Gateway is adopted rather than
 * started, everything it was configured with at its own launch is stale: the
 * local token, the provider settings, the model, the log path. On this machine
 * that produced a Gateway running with no desktop behind it, refusing the
 * Agent its provider credentials 285 times.
 *
 * So ownership stops being a question asked about the OS and becomes a fact
 * written at launch. See docs/PROCESS-OWNERSHIP.md.
 *
 * ## What the record says
 *
 * One `launch_id` per launch, the machine's boot time, and every child with
 * its PID *and* creation time — because a PID alone stops identifying a
 * process the moment the number is reused.
 *
 * ## What reads it
 *
 * The desktop, at startup, to stop the previous launch's children. And every
 * child, continuously: a child whose `launch_id` no longer matches the file
 * stands down on its own. That is what makes adoption impossible — a Gateway
 * from a previous launch does not have to be found, because it leaves.
 */

import { execFileSync } from 'child_process'
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'fs'
import { join } from 'path'
import { randomBytes } from 'crypto'

import { describeProcess, isSameProcess, killTree, type ProcessRecord } from './processes'

export interface RuntimeRecord {
  launchId: string
  /** The machine's boot time, ISO 8601 UTC. PIDs from before it mean nothing. */
  bootId: string
  desktop: ProcessRecord
  children: Record<string, ProcessRecord & { port?: number }>
}

/** Where the record lives, beside the token the same launch issues. */
export function runtimePath(stateDir: string): string {
  return join(stateDir, 'state', 'runtime.json')
}

/**
 * When this machine last booted, as an identity for everything PID-shaped.
 *
 * A record written before the last reboot describes numbers that now belong to
 * other processes, and acting on it is worse than having none. Empty when it
 * cannot be read, which makes the comparison fall through to "trust the
 * record" — the behaviour before this existed.
 */
export function bootId(): string {
  try {
    return execFileSync(
      'powershell',
      [
        '-NoProfile',
        '-Command',
        '(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString("o")'
      ],
      { encoding: 'utf8', windowsHide: true, timeout: 10_000 }
    ).trim()
  } catch {
    return ''
  }
}

export function readRuntime(stateDir: string): RuntimeRecord | null {
  try {
    const found = JSON.parse(readFileSync(runtimePath(stateDir), 'utf8')) as RuntimeRecord
    if (!found || typeof found.launchId !== 'string') return null
    return found
  } catch {
    return null
  }
}

/**
 * Begin a launch: claim ownership before any child exists.
 *
 * Written first so that a child started a moment later can already see which
 * launch it belongs to, and so that a crash between here and the first spawn
 * leaves a record the next launch can clean rather than a mystery.
 */
export function claim(stateDir: string, launchId: string): RuntimeRecord {
  const self = describeProcess(process.pid)
  const record: RuntimeRecord = {
    launchId,
    bootId: bootId(),
    desktop: { pid: process.pid, startedAt: self?.startedAt ?? '' },
    children: {}
  }
  write(stateDir, record)
  return record
}

export function write(stateDir: string, record: RuntimeRecord): void {
  try {
    const target = join(stateDir, 'state')
    mkdirSync(target, { recursive: true })
    writeFileSync(runtimePath(stateDir), JSON.stringify(record, null, 2), 'utf8')
  } catch {
    // Not fatal. Without the record the lifecycle behaves as it did before
    // this file existed, which is imperfect rather than broken.
  }
}

/** Record a child that was just started, by PID and creation time. */
export function remember(
  stateDir: string,
  record: RuntimeRecord,
  name: string,
  pid: number,
  port?: number
): void {
  const facts = describeProcess(pid)
  record.children[name] = {
    pid,
    startedAt: facts?.startedAt ?? '',
    // A fragment distinctive enough to survive PID reuse without pinning the
    // whole command line, which changes with every port and path.
    command: name,
    ...(port === undefined ? {} : { port })
  }
  write(stateDir, record)
}

/**
 * Stop everything the previous launch started. Returns what was stopped.
 *
 * Children that read the record have already left by the time this runs —
 * seeing a new `launch_id` is their signal to exit. This is the fallback for
 * one that is wedged, which is the only role a kill should have.
 */
export function stopPrevious(stateDir: string): string[] {
  const previous = readRuntime(stateDir)
  if (!previous) return []
  const stopped: string[] = []
  // A record from before the last reboot describes PIDs that belong to other
  // programs now. Discard it rather than act on it.
  const booted = bootId()
  if (booted && previous.bootId && previous.bootId !== booted) {
    clear(stateDir)
    return []
  }
  for (const [name, child] of Object.entries(previous.children ?? {})) {
    if (!isSameProcess(child.pid, child)) continue
    if (killTree(child.pid, true)) stopped.push(`${name} (process ${child.pid})`)
  }
  return stopped
}

/**
 * End the launch.
 *
 * The record goes first, then the children, because a child that notices the
 * file has gone is a child already on its way out — and if the desktop dies
 * halfway through this, that is the half worth having done.
 */
export function clear(stateDir: string): void {
  try {
    rmSync(runtimePath(stateDir), { force: true })
  } catch {
    // Nothing to do about it, and the children's other two checks still hold.
  }
}

export function newLaunchId(): string {
  return randomBytes(16).toString('hex')
}

/** Whether a record exists at all, for callers that only need the question. */
export function claimed(stateDir: string): boolean {
  return existsSync(runtimePath(stateDir))
}
