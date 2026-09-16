import { describe, expect, it } from 'vitest'

import { pastedImages } from './paste'

const file = (name: string, type: string): File => new File(['x'], name, { type })

describe('pasting into the composer', () => {
  it('names a screenshot for when it was taken and keeps real names', () => {
    const [shot, named] = pastedImages(
      [file('', 'image/png'), file('diagram.webp', 'image/webp')],
      new Date('2026-09-16T08:30:05Z')
    )
    expect(shot.name).toBe('pasted-2026-09-16T08-30-05.png')
    expect(shot.type).toBe('image/png')
    expect(named.name).toBe('diagram.webp')
  })

  it('numbers several unnamed images and uses their own format', () => {
    const pasted = pastedImages([file('', 'image/jpeg'), file('', 'image/jpeg')])
    expect(pasted[0].name).toMatch(/^pasted-.*\.jpeg$/)
    expect(pasted[1].name).toMatch(/-2\.jpeg$/)
  })

  it('leaves text and other files to the textarea', () => {
    expect(pastedImages([file('notes.txt', 'text/plain')])).toEqual([])
    expect(pastedImages([])).toEqual([])
  })
})
