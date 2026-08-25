import { describe, expect, it } from 'vitest'

/**
 * Whose port is it.
 *
 * `killStrays` is scoped to this install root and leaves another checkout's
 * processes alone — the right rule for a copy somebody is developing in, and
 * the wrong one for a fixed port. Two installations share 8765, so a Gateway
 * left behind by either stops the other starting, and the sweep that could
 * clear it is deliberately looking elsewhere.
 *
 * The question that matters is not which checkout it came from. It is whether
 * anything still owns it: a Gateway whose parent is gone will never be stopped
 * by anything except this, and it held the port overnight while every restart
 * failed to bind.
 */
type Holder = { pid: number } | null
type Details = { command: string; executable: string; parentPid: number } | null

function decide(
  port: number,
  holder: Holder,
  details: Details,
  parentAlive: boolean,
  match = /marvi_gateway/i
): string {
  if (!holder) return ''
  if (!details || !match.test(`${details.command} ${details.executable}`)) {
    return `port ${port} is held by process ${holder.pid}, which is not a Marvi service`
  }
  if (parentAlive) return `port ${port} is held by another running Marvi (process ${holder.pid})`
  return `reclaimed port ${port} from an abandoned Marvi Gateway (process ${holder.pid})`
}

const gateway = {
  command: 'python uvicorn marvi_gateway.app:app',
  executable: 'D:/checkout/.venv/python.exe',
  parentPid: 4
}

describe('reclaiming a port', () => {
  it('takes it back from a Gateway whose owner is gone', () => {
    expect(decide(8765, { pid: 31816 }, gateway, false)).toContain('reclaimed port 8765')
  })

  it('leaves a Gateway that still has an owner alone', () => {
    // Another Marvi is genuinely running. Killing it would be taking a
    // decision that belongs to the person using it.
    expect(decide(8765, { pid: 31816 }, gateway, true)).toContain('another running Marvi')
  })

  it('never kills something that is not ours', () => {
    const other = { command: 'nginx.exe', executable: 'C:/nginx/nginx.exe', parentPid: 0 }
    expect(decide(8765, { pid: 900 }, other, false)).toContain('not a Marvi service')
  })

  it('says nothing when the port is free', () => {
    expect(decide(8765, null, null, false)).toBe('')
  })

  it('refuses when the holder cannot be described', () => {
    // Unknown is not the same as ours, and only one of those is safe to kill.
    expect(decide(8765, { pid: 900 }, null, false)).toContain('not a Marvi service')
  })
})
