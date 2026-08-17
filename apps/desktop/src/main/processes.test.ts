import { spawn } from 'node:child_process'
import { describe, expect, it } from 'vitest'

import { groupSpawnOptions, isAlive, killTree, stopTree } from './processes'

/**
 * The property under test is the one `child.kill()` does not have: a service is
 * `uv` launching Python, so the process that holds the port and the checkout is
 * a *grandchild*. Killing the child alone leaves it running.
 */

const isWindows = process.platform === 'win32'

/** A parent that outlives nothing, and a child that sleeps well past the test. */
function spawnTree(): { pid: number; child: ReturnType<typeof spawn> } {
  const child = isWindows
    ? spawn('cmd', ['/C', 'ping -n 60 127.0.0.1 >NUL'], {
        windowsHide: true,
        ...groupSpawnOptions()
      })
    : spawn('sh', ['-c', 'sleep 60'], { ...groupSpawnOptions() })
  return { pid: child.pid as number, child }
}

async function settle(ms = 1500): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms))
}

describe('process trees', () => {
  it('reports whether a pid is alive', () => {
    expect(isAlive(process.pid)).toBe(true)
    // A pid that cannot exist must not read as alive; getting this backwards is
    // how a wait-for-exit loop never finishes.
    expect(isAlive(4_294_967_294)).toBe(false)
    expect(isAlive(undefined)).toBe(false)
    expect(isAlive(0)).toBe(false)
  })

  it('kills a running process', async () => {
    const { pid, child } = spawnTree()
    expect(isAlive(pid)).toBe(true)

    killTree(pid, true)
    await settle()

    expect(isAlive(pid)).toBe(false)
    child.removeAllListeners()
  }, 20_000)

  it('is safe to call on something already gone', async () => {
    const { pid, child } = spawnTree()
    killTree(pid, true)
    await settle()

    // The desired end state is "not running", which it already is.
    expect(() => killTree(pid, true)).not.toThrow()
    child.removeAllListeners()
  }, 20_000)

  it('ignores a pid that was never ours', () => {
    expect(killTree(undefined)).toBe(false)
    expect(killTree(0)).toBe(false)
    expect(killTree(-1)).toBe(false)
  })

  it('stops a child politely and then insists', async () => {
    const { pid, child } = spawnTree()

    await stopTree(child, 1_000)

    // A Gateway asked to stop gets a moment to close its database; one that
    // ignores the request must not keep the port.
    expect(isAlive(pid)).toBe(false)
  }, 20_000)

  it('does nothing for a null child', async () => {
    await expect(stopTree(null)).resolves.toBeUndefined()
  })

  it('puts children in their own group off Windows', () => {
    // Windows has no process groups, so the tree is walked with taskkill /T
    // instead; detaching there would only orphan the child.
    expect(groupSpawnOptions().detached).toBe(!isWindows)
  })
})
