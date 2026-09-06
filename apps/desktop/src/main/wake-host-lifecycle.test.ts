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
    expect(main).toContain("void wakeAutostart('ensure')")
    expect(main).toContain("if (stdout.trim() !== 'on') return fallback")
  })
})
