/**
 * Windows update handoff, now driven by the small Tauri bootstrap binary
 * (`marvi-bootstrap.exe`) instead of a PowerShell script.
 *
 * Marvi OS cannot update itself while it is running, so the app hands off to
 * the bootstrap, then quits. The bootstrap waits for this process to exit,
 * updates (or installs) the checkout, and relaunches the app. It writes a
 * result marker that this module reads once on the next launch.
 *
 * Channel model:
 *   - `release` (default, opt-out): update to the latest signed `v*` tag.
 *   - `dev` (opt-in): fast-forward `origin/main` and run whatever is there.
 *
 * The bootstrap lives in `%LOCALAPPDATA%\Marvi OS\bin\marvi-bootstrap.exe`;
 * the standalone installer copies itself there during a fresh install.
 */

import { spawn } from 'child_process'
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'fs'
import { join } from 'path'
import type { UpdateChannel, UpdateCheck, UpdateResult } from '../shared/runtime'

const UTF8_BOM = 0xfeff
// Mirrors STATE_DIR_NAME in apps/updater/crates/core/src/lib.rs and
// marvi_gateway/paths.py. All three must agree.
const STATE_DIR_NAME = 'Marvi-OS'
const MARKER_FILE = '.marvi-update-in-progress'
const RESULT_FILE = '.marvi-update-result.json'
const CHANNEL_FILE = '.marvi-update-channel'
const BOOTSTRAP_EXE = 'marvi-bootstrap.exe'

/** Maximum age (ms) after which an in-progress marker is considered stale. */
const STALE_AFTER_MS = 2 * 60 * 60 * 1000

export function updateStateDir(localAppData: string | undefined): string {
  return join(localAppData ?? '', STATE_DIR_NAME)
}

function markerPath(stateDir: string): string {
  return join(stateDir, MARKER_FILE)
}

function resultPath(stateDir: string): string {
  return join(stateDir, RESULT_FILE)
}

function channelPath(stateDir: string): string {
  return join(stateDir, CHANNEL_FILE)
}

/** Resolve the bootstrap binary: explicit env override, else the state dir. */
export function resolveBootstrap(stateDir: string): string | null {
  const override = process.env['MARVI_BOOTSTRAP_EXE']
  if (override && existsSync(override)) return override
  const inBin = join(stateDir, 'bin', BOOTSTRAP_EXE)
  return existsSync(inBin) ? inBin : null
}

export function getUpdateChannel(stateDir: string): UpdateChannel {
  try {
    const raw = readFileSync(channelPath(stateDir), 'utf-8').trim().toLowerCase()
    return raw === 'dev' ? 'dev' : 'release'
  } catch {
    return 'release'
  }
}

export function setUpdateChannel(stateDir: string, channel: UpdateChannel): UpdateChannel {
  const value = channel === 'dev' ? 'dev' : 'release'
  mkdirSync(stateDir, { recursive: true })
  writeFileSync(channelPath(stateDir), `${value}\n`, 'utf-8')
  return value
}

function isProcessAlive(pid: number): boolean {
  if (!Number.isFinite(pid) || pid <= 0) return false
  try {
    process.kill(pid, 0)
    return true
  } catch (error) {
    // EPERM means the process exists but we lack permission to signal it.
    return (error as NodeJS.ErrnoException).code === 'EPERM'
  }
}

interface Marker {
  pid: number
  startedAtMs: number
}

/**
 * True while an update is genuinely mid-flight. A marker whose process is dead,
 * or that is older than the staleness threshold, is treated as recoverable and
 * cleared — fixing the bug where a crashed updater left "UPDATE IN PROGRESS"
 * on screen forever.
 */
export function updateInProgress(stateDir: string): boolean {
  const path = markerPath(stateDir)
  if (!existsSync(path)) return false

  let pid: number | null = null
  let startedAtMs: number | null = null
  try {
    const contents = readFileSync(path, 'utf-8')
    const text = contents.charCodeAt(0) === UTF8_BOM ? contents.slice(1) : contents
    const parsed = JSON.parse(text) as Partial<Marker>
    if (typeof parsed.pid === 'number') pid = parsed.pid
    if (typeof parsed.startedAtMs === 'number') startedAtMs = parsed.startedAtMs
    // Legacy plain-PID marker (from the PowerShell updater).
    if (pid === null && /^\d+$/.test(text.trim())) pid = Number(text.trim())
  } catch {
    /* fall through: treat as in-progress only if the file is fresh */
  }

  const alive = pid !== null ? isProcessAlive(pid) : false
  const fresh = startedAtMs !== null ? Date.now() - startedAtMs < STALE_AFTER_MS : alive

  if (alive && fresh) return true
  try {
    rmSync(path, { force: true })
  } catch {
    /* a stale marker is better than a crash on boot */
  }
  return false
}

/** Read and clear the result the bootstrap left for us. */
export function consumeUpdateResult(stateDir: string): UpdateResult | null {
  const path = resultPath(stateDir)
  if (!existsSync(path)) return null
  let parsed: UpdateResult | null = null
  try {
    const contents = readFileSync(path, 'utf-8')
    const text = contents.charCodeAt(0) === UTF8_BOM ? contents.slice(1) : contents
    const raw = JSON.parse(text) as Partial<UpdateResult>
    if (raw && typeof raw.status === 'string' && typeof raw.message === 'string') {
      parsed = raw as UpdateResult
    }
  } catch {
    parsed = null
  }
  try {
    rmSync(path, { force: true })
  } catch {
    /* a stale result is better than a crash on boot */
  }
  return parsed
}

export function canUpdate(installRoot: string, bootstrap: string | null): boolean {
  return bootstrap !== null && existsSync(join(installRoot, '.git'))
}

/**
 * Read-only availability check: run the bootstrap in `check` mode and parse
 * its JSON. Never mutates the checkout and never quits the app. The check
 * binary exits non-zero on an unavailable update, but still writes a JSON
 * payload (with an `error` field), so stdout is parsed regardless of status.
 */
export function checkForUpdate(
  installRoot: string,
  channel: UpdateChannel,
  bootstrap: string
): Promise<UpdateCheck> {
  return new Promise((resolve) => {
    let stdout = ''
    let child
    try {
      child = spawn(bootstrap, ['check', '--install-root', installRoot, '--channel', channel], {
        stdio: ['ignore', 'pipe', 'ignore']
      })
    } catch {
      resolve({
        channel,
        available: false,
        upToDate: false,
        behindBy: 0,
        error: 'could not run the update check'
      })
      return
    }
    child.stdout?.on('data', (chunk: Buffer) => {
      stdout += chunk.toString()
    })
    child.on('error', () => {
      resolve({
        channel,
        available: false,
        upToDate: false,
        behindBy: 0,
        error: 'could not run the update check'
      })
    })
    child.on('close', () => {
      try {
        const parsed = JSON.parse(stdout) as UpdateCheck
        resolve({ ...parsed, channel })
      } catch {
        resolve({
          channel,
          available: false,
          upToDate: false,
          behindBy: 0,
          error: 'could not parse the update check'
        })
      }
    })
  })
}

export interface HandoffOptions {
  installRoot: string
  channel: UpdateChannel
  desktopPid: number
  relaunchExe?: string
}

/** Build the exact argv for the update handoff (kept pure for tests). */
export function handoffCommand(
  bootstrap: string,
  options: HandoffOptions
): { file: string; args: string[] } {
  const args = [
    'update',
    '--install-root',
    options.installRoot,
    '--channel',
    options.channel,
    '--desktop-pid',
    String(options.desktopPid)
  ]
  if (options.relaunchExe) args.push('--relaunch-exe', options.relaunchExe)
  return { file: bootstrap, args }
}

/**
 * Start the handoff. Returns false when this installation cannot self-update,
 * or when an update is already in flight, so the caller can tell the user
 * rather than quitting into nothing.
 */
export function startUpdate(options: HandoffOptions, bootstrap: string | null): boolean {
  if (process.platform !== 'win32') return false
  if (!bootstrap || !canUpdate(options.installRoot, bootstrap)) return false
  const stateDir = updateStateDir(process.env['LOCALAPPDATA'])
  if (updateInProgress(stateDir)) return false

  const { file, args } = handoffCommand(bootstrap, options)
  const child = spawn(file, args, {
    detached: true,
    stdio: 'ignore'
  })
  child.unref()
  return true
}
