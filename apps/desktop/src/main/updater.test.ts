import { mkdirSync, mkdtempSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { describe, expect, it } from 'vitest'

import {
  canUpdate,
  consumeUpdateResult,
  handoffCommand,
  updateInProgress,
  updateScriptPath,
  updateStateDir
} from './updater'

function workspace(): string {
  return mkdtempSync(join(tmpdir(), 'marvi-update-'))
}

function checkout(): string {
  const root = workspace()
  mkdirSync(join(root, '.git'), { recursive: true })
  mkdirSync(join(root, 'scripts', 'desktop-update'), { recursive: true })
  writeFileSync(updateScriptPath(root), '# updater')
  return root
}

describe('update handoff command', () => {
  it('wraps PowerShell in cmd start, which is what makes it survive our exit', () => {
    const { file, args } = handoffCommand({
      installRoot: 'D:\\Marvi-OS',
      branch: 'main',
      desktopPid: 4242
    })

    expect(file).toBe('cmd.exe')
    // A bare detached powershell is killed before -File is read; the wrapper
    // is load-bearing, so assert its exact shape.
    expect(args.slice(0, 6)).toEqual(['/d', '/s', '/c', 'start', '""', '/min'])
    expect(args).toContain('-NoProfile')
    expect(args).toContain('-ExecutionPolicy')
    expect(args).toContain('Bypass')
  })

  it('passes the checkout, branch and pid the script requires', () => {
    const { args } = handoffCommand({
      installRoot: 'D:\\Marvi-OS',
      branch: 'release',
      desktopPid: 7
    })

    expect(args[args.indexOf('-InstallRoot') + 1]).toBe('D:\\Marvi-OS')
    expect(args[args.indexOf('-Branch') + 1]).toBe('release')
    expect(args[args.indexOf('-DesktopPid') + 1]).toBe('7')
    expect(args[args.indexOf('-File') + 1]).toBe(
      'D:\\Marvi-OS\\scripts\\desktop-update\\windows.ps1'
    )
  })

  it('only asks for a relaunch when it has something to relaunch', () => {
    const without = handoffCommand({ installRoot: 'D:\\x', branch: 'main', desktopPid: 1 })
    const with_ = handoffCommand({
      installRoot: 'D:\\x',
      branch: 'main',
      desktopPid: 1,
      relaunchExe: 'D:\\x\\Marvi-OS.exe'
    })

    expect(without.args).not.toContain('-RelaunchExe')
    expect(with_.args[with_.args.indexOf('-RelaunchExe') + 1]).toBe('D:\\x\\Marvi-OS.exe')
  })
})

describe('update capability', () => {
  it('requires both a git checkout and the updater script', () => {
    expect(canUpdate(checkout())).toBe(true)

    const noGit = workspace()
    mkdirSync(join(noGit, 'scripts', 'desktop-update'), { recursive: true })
    writeFileSync(updateScriptPath(noGit), '# updater')
    expect(canUpdate(noGit)).toBe(false)

    const noScript = workspace()
    mkdirSync(join(noScript, '.git'), { recursive: true })
    expect(canUpdate(noScript)).toBe(false)
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

  it('reports a failed update rather than staying silent', () => {
    const state = workspace()
    writeFileSync(
      join(state, '.marvi-update-result.json'),
      JSON.stringify({
        status: 'failed',
        message: 'The build failed. The previous version was restored.'
      })
    )

    expect(consumeUpdateResult(state)?.status).toBe('failed')
  })

  it('discards a corrupt result instead of crashing on boot', () => {
    const state = workspace()
    writeFileSync(join(state, '.marvi-update-result.json'), '{ not json')

    expect(consumeUpdateResult(state)).toBeNull()
    // And it is gone, so a bad file cannot wedge every future launch.
    expect(consumeUpdateResult(state)).toBeNull()
  })

  it('reads a result written with a UTF-8 BOM', () => {
    // Windows PowerShell 5.1 writes one; JSON.parse rejects it outright, so
    // this silently swallowed every update notification until it was fixed.
    const state = workspace()
    writeFileSync(
      join(state, '.marvi-update-result.json'),
      '﻿' + JSON.stringify({ status: 'ok', message: 'Updated successfully.' })
    )

    expect(consumeUpdateResult(state)?.status).toBe('ok')
  })

  it('is absent when no update has run', () => {
    expect(consumeUpdateResult(workspace())).toBeNull()
  })
})

describe('in-progress marker', () => {
  it('detects an update still running', () => {
    const state = workspace()
    expect(updateInProgress(state)).toBe(false)

    writeFileSync(join(state, '.marvi-update-in-progress'), '1234')
    expect(updateInProgress(state)).toBe(true)
  })
})

describe('state directory', () => {
  it('lives beside the other Marvi OS state', () => {
    expect(updateStateDir('C:\\Users\\x\\AppData\\Local')).toBe(
      join('C:\\Users\\x\\AppData\\Local', 'Marvi OS')
    )
  })
})
