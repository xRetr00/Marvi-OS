import { execFileSync, spawnSync } from 'node:child_process'
import type { ChildProcess } from 'node:child_process'

/**
 * Killing a process and everything it started.
 *
 * `child.kill()` terminates the direct child and nothing else. Marvi's services
 * are all launched through `uv`, which spawns the real work — `uvicorn`, the
 * agent's Python — as a *grandchild*. So killing `uv` leaves a `python.exe`
 * running, holding the virtualenv and the checkout open.
 *
 * That is not a tidy-up detail. On Windows a locked file makes `git checkout`
 * and `npm ci` fail, so an orphan from the last session is enough to break the
 * next update for no reason the user can see. It also means "quit Marvi" leaves
 * a Gateway serving on 8765, which the next launch then fights with.
 *
 * Windows has no process groups, so the tree is walked with `taskkill /T`.
 * Elsewhere the child is put in its own group and the group is signalled.
 */

const KILL_TIMEOUT_MS = 5_000

export function isWindows(): boolean {
  return process.platform === 'win32'
}

/**
 * Spawn options that make a child killable as a unit.
 *
 * On POSIX `detached` starts a new process group, so a negative PID signals the
 * whole group. On Windows it is not needed — `taskkill /T` walks the tree from
 * the parent PID instead.
 */
export function groupSpawnOptions(): { detached: boolean } {
  return { detached: !isWindows() }
}

/** Terminate a PID and every process it started. Never throws. */
export function killTree(pid: number | undefined, force = false): boolean {
  if (!pid || pid <= 0) return false
  try {
    if (isWindows()) {
      // /T is the whole point: without it this is just a slower child.kill().
      const args = ['/PID', String(pid), '/T']
      if (force) args.push('/F')
      const result = spawnSync('taskkill', args, { windowsHide: true, timeout: KILL_TIMEOUT_MS })
      // 128 means the process was already gone, which is the desired end state.
      return result.status === 0 || result.status === 128
    }
    process.kill(-pid, force ? 'SIGKILL' : 'SIGTERM')
    return true
  } catch {
    // Already dead, or not ours to kill. Either way there is nothing to do.
    return false
  }
}

/**
 * Stop a child politely, then insist.
 *
 * A Gateway asked to stop should get the chance to close its database cleanly;
 * one that ignores the request must not be able to keep the port.
 */
export async function stopTree(child: ChildProcess | null, graceMs = 3_000): Promise<void> {
  if (!child || child.pid === undefined) return
  const pid = child.pid
  const exited = new Promise<void>((resolve) => {
    child.once('exit', () => resolve())
    setTimeout(resolve, graceMs)
  })

  killTree(pid, false)
  await exited
  if (isAlive(pid)) killTree(pid, true)
}

export function isAlive(pid: number | undefined): boolean {
  if (!pid || pid <= 0) return false
  try {
    // Signal 0 checks for existence without touching the process.
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

/**
 * Marvi processes left over from a previous session.
 *
 * Found by command line rather than by name: `python.exe` says nothing, but a
 * command line containing `marvi_gateway` or `marvi_agent` is unambiguously
 * ours. Nothing else on the machine is touched.
 */
export function findStrays(installRoot?: string, match?: RegExp): Array<{ pid: number; command: string }> {
  if (!isWindows()) return []
  try {
    const output = execFileSync(
      'powershell',
      [
        '-NoProfile',
        '-Command',
        // ExecutablePath as well as CommandLine. The agent is launched as
        // `uv run --project services/agent ...` -- a relative path -- so its
        // command line never contains the install root, the filter below
        // dropped it, and every restart left the old worker running. Three
        // agents ended up registered against one LiveKit server, and a job
        // dispatched to a stale one simply never ran.
        'Get-CimInstance Win32_Process | ' +
          'ForEach-Object { "$($_.ProcessId)|$($_.ExecutablePath)|$($_.CommandLine)" }'
      ],
      { encoding: 'utf8', windowsHide: true, timeout: 15_000 }
    )
    const mine = match ?? /marvi_gateway|marvi_agent|livekit-server/i
    return output
      .split(/\r?\n/)
      .map((line) => {
        const parts = line.split('|')
        if (parts.length < 3) return null
        const pid = Number(parts[0])
        const executable = parts[1] ?? ''
        const command = parts.slice(2).join('|')
        if (!Number.isFinite(pid) || pid === process.pid) return null
        if (!mine.test(command)) return null
        // When an install root is given, only processes running out of *that*
        // checkout count. A second checkout someone is developing in is theirs.
        //
        // Matched against the executable path as well as the command line: a
        // service started with a relative --project path carries the root in
        // neither its arguments nor its name, and only the interpreter's own
        // location says where it came from.
        if (installRoot) {
          const root = installRoot.toLowerCase()
          const inside =
            command.toLowerCase().includes(root) || executable.toLowerCase().startsWith(root)
          if (!inside) return null
        }
        return { pid, command }
      })
      .filter((entry): entry is { pid: number; command: string } => entry !== null)
  } catch {
    return []
  }
}

/** Kill anything left from a previous session. Returns how many were stopped. */
export function killStrays(installRoot?: string, match?: RegExp): number {
  let stopped = 0
  for (const stray of findStrays(installRoot, match)) {
    if (killTree(stray.pid, true)) stopped += 1
  }
  return stopped
}
