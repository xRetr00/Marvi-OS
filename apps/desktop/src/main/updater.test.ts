import { mkdirSync, mkdtempSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { describe, expect, it } from 'vitest'

import {
  canUpdate,
  consumeUpdateResult,
  getUpdateChannel,
  handoffCommand,
  setUpdateChannel,
  startUpdate,
  updateInProgress,
  updateStateDir
} from './updater'

function workspace(): string {
  return mkdtempSync(join(tmpdir(), 'marvi-update-'))
}

function checkout(): string {
  const root = workspace()
  mkdirSync(join(root, '.git'), { recursive: true })
  return root
}

function marker(state: string, payload: unknown): void {
  writeFileSync(join(state, '.marvi-update-in-progress'), JSON.stringify(payload))
}

describe('update handoff command', () => {
  it('spawns the bootstrap binary in update mode', () => {
    const { file, args, cwd } = handoffCommand('C:\\bin\\marvi-bootstrap.exe', {
      installRoot: 'D:\\Marvi-OS',
      channel: 'release',
      desktopPid: 4242
    })

    expect(file).toBe('C:\\bin\\marvi-bootstrap.exe')
    expect(cwd).toBe('D:\\Marvi-OS')
    expect(args[0]).toBe('update')
    expect(args[args.indexOf('--install-root') + 1]).toBe('D:\\Marvi-OS')
    expect(args[args.indexOf('--channel') + 1]).toBe('release')
    expect(args[args.indexOf('--desktop-pid') + 1]).toBe('4242')
  })

  it('passes the dev channel through', () => {
    const { args } = handoffCommand('bootstrap.exe', {
      installRoot: 'D:\\Marvi-OS',
      channel: 'dev',
      desktopPid: 7
    })
    expect(args[args.indexOf('--channel') + 1]).toBe('dev')
  })

  it('only asks for a relaunch when it has something to relaunch', () => {
    const without = handoffCommand('bootstrap.exe', {
      installRoot: 'D:\\x',
      channel: 'release',
      desktopPid: 1
    })
    const with_ = handoffCommand('bootstrap.exe', {
      installRoot: 'D:\\x',
      channel: 'release',
      desktopPid: 1,
      relaunchExe: 'D:\\x\\Marvi-OS.exe'
    })

    expect(without.args).not.toContain('--relaunch-exe')
    expect(with_.args[with_.args.indexOf('--relaunch-exe') + 1]).toBe('D:\\x\\Marvi-OS.exe')
  })
})

describe('update capability', () => {
  it('requires a git checkout and a bootstrap binary', () => {
    expect(canUpdate(checkout(), 'bootstrap.exe')).toBe(true)

    const noGit = workspace()
    expect(canUpdate(noGit, 'bootstrap.exe')).toBe(false)

    expect(canUpdate(checkout(), null)).toBe(false)
  })
})

describe('update result', () => {
  it('reads the result the updater left and clears it', () => {
    const state = workspace()
    writeFileSync(
      join(state, '.marvi-update-result.json'),
      JSON.stringify({ status: 'ok', message: 'Updated successfully.', from: 'a', to: 'b' })
    )

    const first = consumeUpdateResult(state)
    const second = consumeUpdateResult(state)

    expect(first?.status).toBe('ok')
    expect(first?.message).toBe('Updated successfully.')
    // Consumed, so it is not re-announced on every launch.
    expect(second).toBeNull()
  })

  it('discards a corrupt result instead of crashing on boot', () => {
    const state = workspace()
    writeFileSync(join(state, '.marvi-update-result.json'), '{ not json')

    expect(consumeUpdateResult(state)).toBeNull()
    expect(consumeUpdateResult(state)).toBeNull()
  })

  it('reads a result written with a UTF-8 BOM', () => {
    const state = workspace()
    writeFileSync(
      join(state, '.marvi-update-result.json'),
      '\ufeff' + JSON.stringify({ status: 'ok', message: 'Updated successfully.' })
    )

    expect(consumeUpdateResult(state)?.status).toBe('ok')
  })
})

describe('in-progress marker', () => {
  it('is absent when no update has run', () => {
    expect(updateInProgress(workspace())).toBe(false)
  })

  it('detects a live, recent update', () => {
    const state = workspace()
    marker(state, { pid: process.pid, startedAtMs: Date.now() })
    expect(updateInProgress(state)).toBe(true)
  })

  it('clears a marker whose process is dead', () => {
    const state = workspace()
    // A pid that cannot be alive: the liveness check uses process.kill(pid, 0).
    marker(state, { pid: 0, startedAtMs: Date.now() })
    expect(updateInProgress(state)).toBe(false)
    expect(updateInProgress(state)).toBe(false)
  })

  it('clears a stale marker even if the pid looks alive', () => {
    const state = workspace()
    marker(state, { pid: process.pid, startedAtMs: Date.now() - 3 * 60 * 60 * 1000 })
    expect(updateInProgress(state)).toBe(false)
  })

  it('clears a legacy plain-pid marker when that pid is dead', () => {
    const state = workspace()
    writeFileSync(join(state, '.marvi-update-in-progress'), '0')
    expect(updateInProgress(state)).toBe(false)
  })
})

describe('channel persistence', () => {
  it('defaults to release and round-trips dev', () => {
    const state = workspace()
    expect(getUpdateChannel(state)).toBe('release')
    expect(setUpdateChannel(state, 'dev')).toBe('dev')
    expect(getUpdateChannel(state)).toBe('dev')
    expect(setUpdateChannel(state, 'release')).toBe('release')
  })
})

describe('start update gating', () => {
  it('refuses when there is no bootstrap', () => {
    const root = checkout()
    const ok = startUpdate({ installRoot: root, channel: 'release', desktopPid: process.pid }, null)
    expect(ok).toBe(false)
  })

  it('refuses when there is no git checkout', () => {
    const ok = startUpdate(
      { installRoot: workspace(), channel: 'release', desktopPid: process.pid },
      'bootstrap.exe'
    )
    expect(ok).toBe(false)
  })
})

describe('state directory', () => {
  it('is the one root the Rust core and the Gateway also use', () => {
    // STATE_DIR_NAME in apps/updater/crates/core/src/lib.rs and
    // marvi_gateway/paths.py must match this. Three copies of a folder name is
    // three chances for one of them to drift.
    expect(updateStateDir('C:\\Users\\x\\AppData\\Local')).toBe(
      join('C:\\Users\\x\\AppData\\Local', 'Marvi-OS')
    )
  })

  it('has no space in it', () => {
    // A space in a path is a nuisance in every shell, and this one is passed to
    // PowerShell by the update handoff.
    expect(updateStateDir('C:\\x')).not.toContain(' ')
  })
})
