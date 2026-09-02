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
export function findStrays(
  installRoot?: string,
  match?: RegExp
): Array<{ pid: number; command: string }> {
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

/**
 * Who is listening on a port, as something a person can act on.
 *
 * A Gateway that cannot bind writes `[Errno 10048] only one usage of each
 * socket address` and exits; the supervisor restarts it, it fails the same
 * way, and the loop says nothing about *what* is already there. The answer on
 * this machine was a Gateway from a second checkout that had been running
 * since the previous evening — invisible from inside Marvi, because
 * `killStrays` is scoped to this install root and correctly leaves another
 * checkout's processes alone.
 *
 * Identifying is not killing. Another checkout's Gateway may be something
 * somebody is using.
 */
export function whoHasPort(port: number): { pid: number; command: string } | null {
  if (!isWindows()) return null
  try {
    const output = execFileSync(
      'powershell',
      [
        '-NoProfile',
        '-Command',
        `$c = Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue | ` +
          'Select-Object -First 1; if ($c) { $p = Get-CimInstance Win32_Process -Filter ' +
          '"ProcessId=$($c.OwningProcess)"; "$($c.OwningProcess)|$($p.ExecutablePath)" }'
      ],
      { encoding: 'utf8', windowsHide: true, timeout: 10_000 }
    ).trim()
    if (!output) return null
    const [pid, command] = output.split('|')
    return { pid: Number(pid), command: (command ?? '').trim() }
  } catch {
    return null
  }
}

/**
 * Take back a port held by a Marvi that no longer has an owner.
 *
 * `killStrays` is scoped to this install root and leaves another checkout's
 * processes alone, which is the right rule for a second copy someone is
 * developing in. It is the wrong rule for a fixed port: two installations
 * share 8765, so a Gateway left behind by either one stops the other starting,
 * and the sweep that could have cleared it is deliberately looking elsewhere.
 *
 * The distinction that matters is not which checkout it came from. It is
 * whether anything still owns it. A Gateway whose parent is gone is nobody's:
 * the desktop that started it has exited, it will never be stopped by anything
 * except this, and it held the port overnight while every restart failed to
 * bind.
 *
 * So: only a process that is recognisably a Marvi Gateway, only when its
 * parent no longer exists, and never anything else on that port -- something
 * unrelated listening on 8765 is a message for the user, not a process to
 * kill.
 */
export function reclaimPort(port: number, match = /marvi_gateway/i): string {
  const holder = whoHasPort(port)
  if (!holder) return ''
  const details = describeProcess(holder.pid)
  if (!details || !match.test(`${details.command} ${details.executable}`)) {
    return `port ${port} is held by process ${holder.pid}, which is not a Marvi service`
  }
  // The parent, verified rather than merely counted.
  //
  // `isAlive(parentPid)` was true of a parent that had exited and whose PID
  // had been reused, so an abandoned Gateway read as "another running Marvi"
  // and was left holding the port -- which is how one survived with no desktop
  // behind it, refusing the Agent its credentials 285 times.
  const parent = describeProcess(details.parentPid)
  if (parent) {
    return `port ${port} is held by another running Marvi (process ${holder.pid})`
  }
  return killTree(holder.pid, true)
    ? `reclaimed port ${port} from an abandoned Marvi Gateway (process ${holder.pid})`
    : `port ${port} is held by process ${holder.pid} and it could not be stopped`
}

/** One process's command line, image path, parent and creation time, or null. */
export function describeProcess(pid: number): ProcessFacts | null {
  if (!isWindows()) return null
  try {
    const output = execFileSync(
      'powershell',
      [
        '-NoProfile',
        '-Command',
        `$p = Get-CimInstance Win32_Process -Filter "ProcessId=${pid}"; ` +
          'if ($p) { $t = $p.CreationDate.ToUniversalTime().ToString("o"); ' +
          '"$($p.ParentProcessId)|$t|$($p.ExecutablePath)|$($p.CommandLine)" }'
      ],
      { encoding: 'utf8', windowsHide: true, timeout: 10_000 }
    ).trim()
    if (!output) return null
    const parts = output.split('|')
    return {
      parentPid: Number(parts[0]),
      startedAt: parts[1] ?? '',
      executable: parts[2] ?? '',
      command: parts.slice(3).join('|')
    }
  } catch {
    return null
  }
}

/**
 * Whether the process at `pid` is still the one that was recorded there.
 *
 * `isAlive` answers "does a process have this number", which is not the same
 * question and is the one the lifecycle kept asking. Windows recycles PIDs
 * within minutes on a busy machine, so "the Gateway's parent is alive" was
 * true of a parent that had exited hours earlier and whose number now belonged
 * to something unrelated -- and the launch that asked adopted an abandoned
 * Gateway on the strength of it.
 *
 * A process is the same process when the number *and* the creation time match.
 * The command line is compared too when one was recorded, because the cheapest
 * way to be sure is to check the thing that is expensive to fake.
 */
export function isSameProcess(pid: number | undefined, recorded: ProcessRecord): boolean {
  if (!pid || pid <= 0 || !isAlive(pid)) return false
  if (!recorded.startedAt) {
    // Nothing to compare against: an older record, or a platform where the
    // creation time could not be read. Falls back to existence, which is what
    // this replaced -- no worse, and it says so.
    return true
  }
  const facts = describeProcess(pid)
  if (!facts) return false
  if (facts.startedAt !== recorded.startedAt) return false
  if (recorded.command && facts.command && !facts.command.includes(recorded.command)) {
    return false
  }
  return true
}

export interface ProcessFacts {
  command: string
  executable: string
  parentPid: number
  /** ISO 8601, UTC. Empty when it could not be read. */
  startedAt: string
}

/** Enough to recognise a process again after its PID has been reused. */
export interface ProcessRecord {
  pid: number
  startedAt: string
  /** A distinctive fragment of the command line, or empty to skip the check. */
  command?: string
}
