import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

const main = readFileSync(join(__dirname, 'index.ts'), 'utf8')

describe('wake host lifecycle', () => {
  it('stops the live listener when the user switches it off', () => {
    expect(main).toContain("execFileAsync(listener, ['--stop']")
    expect(main).toContain('if (!on) return { autostart: false, running: false }')
  })

  it('restores an enabled listener after an updater relaunch', () => {
    expect(main).toContain('startWakeWatchdog()')
    expect(main).toContain("await wakeAutostart('ensure')")
    expect(main).toContain("if (stdout.trim() !== 'on') return fallback")
  })

  it('gates crash recovery on the user setting and a stale heartbeat', () => {
    expect(main).toContain('!wakeAutoRestartEnabled() || wakeListenerFresh()')
    expect(main).toContain('MARVI_WAKE_AUTO_RESTART=')
    expect(main).toContain('now - heartbeat <= WAKE_STALE_MS')
  })
})
