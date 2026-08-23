import { describe, expect, it } from 'vitest'

import { encodePetHostCommand, resolvePetHostPaths } from './pet-host'

describe('native pet host protocol', () => {
  it('writes one bounded JSON command per line', () => {
    expect(encodePetHostCommand({ type: 'look', direction: 15 })).toBe(
      '{"type":"look","direction":15}\n'
    )
    expect(encodePetHostCommand({ type: 'bounds', x: 10, y: 20, width: 96, height: 104 })).toBe(
      '{"type":"bounds","x":10,"y":20,"width":96,"height":104}\n'
    )
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
