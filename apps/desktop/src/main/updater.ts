/**
 * Windows update handoff.
 *
 * Marvi OS cannot update itself while it is running: the build overwrites files
 * the running process holds open. So the app hands off to a PowerShell script
 * that lives in the checkout, then quits. The script waits for this process to
 * exit, updates, and relaunches.
 *
 * The script is deliberately repository-owned rather than bundled: a frozen
 * binary can never fix its own updater, so update bugs would outlive their
 * fixes. Adapted from the tested predecessor handoff — see docs/UPSTREAM.md.
 *
 * The `cmd /d /s /c start` wrapper is not decoration. A bare detached, hidden
 * PowerShell is killed when its parent exits, before `-File` is ever read.
 */

import { spawn } from 'child_process'
import { existsSync, readFileSync, rmSync } from 'fs'
import { join } from 'path'

export interface UpdateResult {
  status: 'ok' | 'failed' | 'aborted' | 'skipped'
  message: string
  from?: string
  to?: string
  branch?: string
  finishedAt?: string
}

export interface HandoffOptions {
  installRoot: string
  branch: string
  desktopPid: number
  relaunchExe?: string
}

export function updateStateDir(localAppData: string | undefined): string {
  return join(localAppData ?? '', 'Marvi OS')
}

export function updateScriptPath(installRoot: string): string {
  return join(installRoot, 'scripts', 'desktop-update', 'windows.ps1')
}

/**
 * Build the exact argv for the handoff. Kept pure so the wrapper shape can be
 * asserted in tests — getting it wrong fails silently at runtime, because the
 * script simply never starts.
 */
export function handoffCommand(options: HandoffOptions): { file: string; args: string[] } {
  const script = updateScriptPath(options.installRoot)
  const args = [
    '/d',
    '/s',
    '/c',
    'start',
    '""',
    '/min',
    'powershell',
    '-NoProfile',
    '-ExecutionPolicy',
    'Bypass',
    '-File',
    script,
    '-InstallRoot',
    options.installRoot,
    '-Branch',
    options.branch,
    '-DesktopPid',
    String(options.desktopPid)
  ]
  if (options.relaunchExe) args.push('-RelaunchExe', options.relaunchExe)
  return { file: 'cmd.exe', args }
}

/** Read and clear the result the updater left for us. */
export function consumeUpdateResult(stateDir: string): UpdateResult | null {
  const path = join(stateDir, '.marvi-update-result.json')
  if (!existsSync(path)) return null
  let parsed: UpdateResult | null = null
  try {
    // Written by PowerShell, which may prepend a UTF-8 BOM; JSON.parse rejects it.
    const text = readFileSync(path, 'utf-8').replace(/^﻿/, '')
    const raw = JSON.parse(text) as Partial<UpdateResult>
    if (raw && typeof raw.status === 'string' && typeof raw.message === 'string') {
      parsed = raw as UpdateResult
    }
  } catch {
    parsed = null
  }
  // Consume it either way: a result we cannot read is not one we should keep
  // showing on every launch.
  try {
    rmSync(path, { force: true })
  } catch {
    /* a stale result is better than a crash on boot */
  }
  return parsed
}

/** True while an update is mid-flight, so a relaunched app does not fight it. */
export function updateInProgress(stateDir: string): boolean {
  return existsSync(join(stateDir, '.marvi-update-in-progress'))
}

export function canUpdate(installRoot: string): boolean {
  return existsSync(join(installRoot, '.git')) && existsSync(updateScriptPath(installRoot))
}

/**
 * Start the handoff. Returns false when this installation cannot self-update,
 * so the caller can tell the user rather than quitting into nothing.
 */
export function startUpdate(options: HandoffOptions): boolean {
  if (process.platform !== 'win32' || !canUpdate(options.installRoot)) return false
  const { file, args } = handoffCommand(options)
  const child = spawn(file, args, {
    detached: true,
    stdio: 'ignore',
    windowsVerbatimArguments: true
  })
  child.unref()
  return true
}
