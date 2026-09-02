/**
 * Ownership is written down, not inferred.
 *
 * The lifecycle used to ask the operating system who owned a process — adopt
 * the port holder if its parent PID is alive, kill it if not — and every
 * branch of that is wrong in some case. On this machine it left a Gateway
 * running with no desktop behind it, refusing the Agent its provider
 * credentials 285 times. See docs/PROCESS-OWNERSHIP.md.
 */

import { mkdtempSync, readFileSync, rmSync, writeFileSync, mkdirSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('./processes', () => ({
  describeProcess: (pid: number) =>
    pid === 4242 ? null : { command: 'x', executable: 'x', parentPid: 1, startedAt: `t-${pid}` },
  isSameProcess: (pid: number | undefined, recorded: { startedAt: string }) =>
    pid !== undefined && recorded.startedAt === `t-${pid}`,
  killTree: (pid: number) => pid !== 9999
}))

const ownership = await import('./ownership')

const made: string[] = []

function home(): string {
  const path = mkdtempSync(join(tmpdir(), 'marvi-own-'))
  made.push(path)
  return path
}

afterEach(() => {
  for (const path of made.splice(0)) rmSync(path, { recursive: true, force: true })
})

describe('the ownership record', () => {
  it('is claimed before any child exists', () => {
    const state = home()
    const record = ownership.claim(state, 'launch-one')

    expect(record.launchId).toBe('launch-one')
    expect(record.children).toEqual({})
    const written = JSON.parse(readFileSync(ownership.runtimePath(state), 'utf8'))
    expect(written.launchId).toBe('launch-one')
  })

  it('records a child by pid and creation time', () => {
    // The creation time is the half that matters: a PID alone stops
    // identifying a process the moment the number is reused, which is exactly
    // how an abandoned Gateway read as "another running Marvi".
    const state = home()
    const record = ownership.claim(state, 'launch-one')
    ownership.remember(state, record, 'gateway', 1234, 8765)

    const written = JSON.parse(readFileSync(ownership.runtimePath(state), 'utf8'))
    expect(written.children.gateway).toMatchObject({
      pid: 1234,
      startedAt: 't-1234',
      port: 8765
    })
  })

  it('stops the previous launch by recorded identity', () => {
    const state = home()
    const record = ownership.claim(state, 'launch-one')
    ownership.remember(state, record, 'gateway', 1234)

    expect(ownership.stopPrevious(state)).toEqual(['gateway (process 1234)'])
  })

  it('leaves a recycled pid alone', () => {
    // The record says pid 1234 started at `t-1234`. A process with that number
    // whose creation time differs is a different program that happens to have
    // inherited the number, and killing it would be killing a stranger.
    const state = home()
    mkdirSync(join(state, 'state'), { recursive: true })
    writeFileSync(
      ownership.runtimePath(state),
      JSON.stringify({
        launchId: 'launch-one',
        bootId: ownership.bootId(),
        desktop: { pid: 1, startedAt: 't-1' },
        children: { gateway: { pid: 1234, startedAt: 'a-different-time' } }
      }),
      'utf8'
    )

    expect(ownership.stopPrevious(state)).toEqual([])
  })

  it('discards a record from before the last reboot', () => {
    // Every PID in it belongs to some other program now, so acting on it is
    // worse than having no record at all.
    const state = home()
    mkdirSync(join(state, 'state'), { recursive: true })
    writeFileSync(
      ownership.runtimePath(state),
      JSON.stringify({
        launchId: 'launch-one',
        bootId: '1999-01-01T00:00:00.0000000Z',
        desktop: { pid: 1, startedAt: 't-1' },
        children: { gateway: { pid: 1234, startedAt: 't-1234' } }
      }),
      'utf8'
    )

    expect(ownership.stopPrevious(state)).toEqual([])
    expect(ownership.claimed(state)).toBe(false)
  })

  it('is cleared on shutdown', () => {
    const state = home()
    ownership.claim(state, 'launch-one')
    expect(ownership.claimed(state)).toBe(true)
    ownership.clear(state)
    expect(ownership.claimed(state)).toBe(false)
    // Twice is not an error: shutdown can run more than once.
    ownership.clear(state)
  })

  it('survives a missing or corrupt record', () => {
    const state = home()
    expect(ownership.readRuntime(state)).toBeNull()
    expect(ownership.stopPrevious(state)).toEqual([])

    mkdirSync(join(state, 'state'), { recursive: true })
    writeFileSync(ownership.runtimePath(state), '{not json', 'utf8')
    expect(ownership.readRuntime(state)).toBeNull()
    expect(ownership.stopPrevious(state)).toEqual([])
  })

  it('gives every launch a different id', () => {
    expect(ownership.newLaunchId()).not.toBe(ownership.newLaunchId())
  })
})
