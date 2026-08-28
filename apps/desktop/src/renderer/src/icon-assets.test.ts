import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { inflateSync } from 'node:zlib'
import { describe, expect, it } from 'vitest'

const repository = resolve(__dirname, '../../../../..')

function png(path: string): {
  width: number
  height: number
  alphaAt: (x: number, y: number) => number
} {
  const file = readFileSync(path)
  expect(file.subarray(1, 4).toString('ascii')).toBe('PNG')
  const width = file.readUInt32BE(16)
  const height = file.readUInt32BE(20)
  expect(file[24]).toBe(8)
  expect(file[25]).toBe(6)
  expect(file[28]).toBe(0)

  const chunks: Buffer[] = []
  for (let offset = 8; offset < file.length;) {
    const length = file.readUInt32BE(offset)
    const type = file.subarray(offset + 4, offset + 8).toString('ascii')
    if (type === 'IDAT') chunks.push(file.subarray(offset + 8, offset + 8 + length))
    offset += 12 + length
  }
  const packed = inflateSync(Buffer.concat(chunks))
  const stride = width * 4
  const pixels = Buffer.alloc(stride * height)

  for (let y = 0; y < height; y += 1) {
    const filter = packed[y * (stride + 1)]
    for (let x = 0; x < stride; x += 1) {
      const raw = packed[y * (stride + 1) + x + 1]
      const left = x >= 4 ? pixels[y * stride + x - 4] : 0
      const up = y > 0 ? pixels[(y - 1) * stride + x] : 0
      const upperLeft = y > 0 && x >= 4 ? pixels[(y - 1) * stride + x - 4] : 0
      const paeth = (): number => {
        const p = left + up - upperLeft
        const distances = [Math.abs(p - left), Math.abs(p - up), Math.abs(p - upperLeft)]
        return distances[0] <= distances[1] && distances[0] <= distances[2]
          ? left
          : distances[1] <= distances[2]
            ? up
            : upperLeft
      }
      const predictor = [0, left, up, Math.floor((left + up) / 2), paeth()][filter]
      pixels[y * stride + x] = (raw + predictor) & 0xff
    }
  }

  return {
    width,
    height,
    alphaAt: (x, y) => pixels[y * stride + x * 4 + 3]
  }
}

function icoSizes(path: string): number[] {
  const file = readFileSync(path)
  expect(file.readUInt16LE(0)).toBe(0)
  expect(file.readUInt16LE(2)).toBe(1)
  return Array.from({ length: file.readUInt16LE(4) }, (_, index) => {
    const width = file[6 + index * 16]
    return width === 0 ? 256 : width
  })
}

describe('Marvi icon assets', () => {
  const pngs: Array<[string, number]> = [
    ['apps/desktop/build/icon.png', 512],
    ['apps/desktop/resources/icon.png', 256],
    ['apps/desktop/resources/tray-icon.png', 32],
    ['apps/desktop/src/renderer/src/assets/app-icon.png', 256],
    ['apps/updater/src-tauri/icons/128x128.png', 128],
    ['apps/updater/src-tauri/icons/32x32.png', 32]
  ]

  it.each(pngs)('%s is square, transparent, and rounded', (relative, size) => {
    const image = png(join(repository, relative))
    expect([image.width, image.height]).toEqual([size, size])
    expect(image.alphaAt(0, 0)).toBe(0)
    expect(image.alphaAt(Math.floor(size / 2), Math.floor(size / 2))).toBeGreaterThan(0)
  })

  it('packages purpose-sized Windows frames', () => {
    expect(icoSizes(join(repository, 'apps/desktop/build/icon.ico'))).toEqual([
      256, 128, 64, 48, 32, 24, 16
    ])
    expect(icoSizes(join(repository, 'apps/desktop/resources/tray-icon.ico'))).toEqual([
      32, 24, 20, 16
    ])
    expect(icoSizes(join(repository, 'apps/updater/src-tauri/icons/icon.ico'))).toEqual([
      256, 128, 64, 48, 32, 24, 16
    ])
  })

  it('uses the PNG renderer asset and the executable icon for shortcuts', () => {
    const app = readFileSync(join(__dirname, 'App.tsx'), 'utf8')
    const handoff = readFileSync(
      join(repository, 'apps/updater/crates/core/src/handoff.rs'),
      'utf8'
    )
    expect(app).toContain("import appIcon from './assets/app-icon.png'")
    expect(handoff).toContain("$link.IconLocation = '{target},0'")
  })
})
