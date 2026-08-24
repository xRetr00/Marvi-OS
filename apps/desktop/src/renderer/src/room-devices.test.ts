import { describe, expect, it } from 'vitest'

import { deviceStanding, deviceStory, deviceTone } from './room-devices'

describe('what to say about a device that is not working', () => {
  it('says the missing driver first and stops there', () => {
    // The bulb showed "given up after 11,359 failed attempts" while the real
    // story was that tinytuya had never been installed. Eleven thousand
    // attempts is a true number and a useless one when nothing was ever able
    // to talk to the device: it reads as a broken bulb and sends somebody to
    // check a plug that was fine.
    const story = deviceStory(
      'tinytuya',
      { configured: true, online: false },
      { circuit_open: true, consecutive_failures: 11359 }
    )

    expect(story).toContain('tinytuya is not installed')
    expect(story).not.toContain('11,359')
  })

  it('does not call a missing driver an error', () => {
    // Nothing is wrong with the device. Nobody installed the library.
    expect(deviceTone('tinytuya', { configured: true, online: false })).toBe('neutral')
    expect(deviceStanding('tinytuya', { configured: true, online: false })).toBe('no driver')
  })

  it('asks for configuration before reporting failures', () => {
    expect(deviceStory('', { configured: false }, { circuit_open: true })).toContain(
      'No address or key'
    )
  })

  it('treats a device switched off at the wall as normal', () => {
    // A lamp turned off is a thing people do to lamps, not a fault, and the
    // sidecar picks it up again on its own.
    const story = deviceStory(
      '',
      { configured: true, online: false },
      { circuit_open: true, consecutive_failures: 11359 }
    )

    expect(story).toContain('11,359')
    expect(story).toContain('pick up again by itself')
  })

  it('shows the address when a configured device is simply working', () => {
    expect(deviceStory('', { configured: true, online: true, ip: '192.168.1.40' }, {})).toBe(
      '192.168.1.40'
    )
  })

  it('separates configured-but-silent from configured-and-given-up', () => {
    expect(deviceStory('', { configured: true }, {})).toContain('nothing has answered yet')
  })

  it('reports a working device as ready and a silent one as a problem', () => {
    expect(deviceTone('', { configured: true, online: true })).toBe('ready')
    expect(deviceTone('', { configured: true, online: false })).toBe('danger')
    expect(deviceTone('', { configured: false })).toBe('neutral')
  })
})
