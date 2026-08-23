import { describe, expect, it } from 'vitest'

import {
  encodePetHostCommand,
  parsePetHostEvent,
  petActionPage,
  petTaskCount,
  resolvePetHostPaths
} from './pet-host'

describe('native pet host protocol', () => {
  it('writes one bounded JSON command per line', () => {
    expect(encodePetHostCommand({ type: 'look', direction: 15 })).toBe(
      '{"type":"look","direction":15}\n'
    )
    expect(encodePetHostCommand({ type: 'bounds', x: 10, y: 20, width: 96, height: 104 })).toBe(
      '{"type":"bounds","x":10,"y":20,"width":96,"height":104}\n'
    )
  })

  it('accepts only known helper actions', () => {
    expect(parsePetHostEvent('{"type":"action","action":"voice"}')).toEqual({
      type: 'action',
      action: 'voice'
    })
    expect(parsePetHostEvent('{"type":"action","action":"delete"}')).toBeNull()
    expect(parsePetHostEvent('noise')).toBeNull()
  })

  it('reports the single authoritative active operation', () => {
    expect(petTaskCount('thinking')).toBe(1)
    expect(petTaskCount('action')).toBe(1)
    expect(petTaskCount('confirmation')).toBe(1)
    expect(petTaskCount('ready')).toBe(0)
  })

  it('routes controls to existing Marvi surfaces', () => {
    expect(petActionPage('voice')).toBe('Voice')
    expect(petActionPage('tasks')).toBe('Activity')
  })

  it('resolves development artifacts outside the desktop package', () => {
    const paths = resolvePetHostPaths({
      isPackaged: false,
      getAppPath: () => 'D:\\repo\\apps\\desktop'
    })
    expect(paths.executable.replaceAll('\\', '/')).toContain(
      '/apps/pet-host/target/release/marvi-pet-host.exe'
    )
    expect(paths.atlas.replaceAll('\\', '/')).toContain('/assets/pet/marvi/spritesheet.webp')
  })
})
