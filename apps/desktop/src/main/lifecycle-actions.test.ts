import { describe, expect, it, vi } from 'vitest'

import { restartApplication, shutdownApplication } from './lifecycle-actions'

describe('application lifecycle actions', () => {
  it('schedules a relaunch before entering the normal teardown path', () => {
    const calls: string[] = []
    restartApplication({
      relaunch: () => calls.push('relaunch'),
      quit: () => calls.push('quit')
    })

    expect(calls).toEqual(['relaunch', 'quit'])
  })

  it('uses the normal quit path for a full shutdown', () => {
    const quit = vi.fn()
    shutdownApplication({ quit, relaunch: vi.fn() })

    expect(quit).toHaveBeenCalledOnce()
  })
})
