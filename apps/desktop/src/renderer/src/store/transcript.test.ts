import { beforeEach, describe, expect, it } from 'vitest'

import { $heard, $spoken, applyTranscript, clearTranscript } from './transcript'

/**
 * Subtitles are judged on one thing: do they read as the sentence being said,
 * or as a UI arguing with itself. A recogniser revises its guess several times
 * a second, so the same segment arrives again, longer — growing in place is the
 * whole behaviour, and replacing the line instead is the stutter people notice.
 */
beforeEach(() => clearTranscript())

const line = (over: Partial<Parameters<typeof applyTranscript>[0]> = {}) => ({
  role: 'user' as const,
  text: 'turn on',
  final: false,
  id: 'seg-1',
  ...over
})

describe('a segment being revised', () => {
  it('grows in place rather than replacing the line', () => {
    applyTranscript(line({ text: 'turn' }))
    applyTranscript(line({ text: 'turn on the' }))

    expect($heard.get()?.text).toBe('turn on the')
  })

  it('settles when the recogniser commits', () => {
    applyTranscript(line({ text: 'turn on the light', final: false }))
    applyTranscript(line({ text: 'turn on the light', final: true }))

    expect($heard.get()?.final).toBe(true)
  })

  it('replaces the line when a new segment starts', () => {
    applyTranscript(line({ text: 'turn on the light', final: true }))
    applyTranscript(line({ id: 'seg-2', text: 'and the lamp' }))

    // Not appended: this is a glance while talking, not a transcript.
    expect($heard.get()?.text).toBe('and the lamp')
  })
})

describe('the two sides', () => {
  it('are kept apart', () => {
    applyTranscript(line({ role: 'user', text: 'is it on?' }))
    applyTranscript(line({ role: 'marvi', id: 'seg-9', text: 'Yes, it is.' }))

    expect($heard.get()?.text).toBe('is it on?')
    expect($spoken.get()?.text).toBe('Yes, it is.')
  })

  it('do not overwrite each other on a shared segment id', () => {
    applyTranscript(line({ role: 'user', text: 'hello' }))
    applyTranscript(line({ role: 'marvi', text: 'hello back' }))

    expect($heard.get()?.text).toBe('hello')
  })
})

describe('leaving the call', () => {
  it('clears both, so the last exchange does not linger as if still live', () => {
    applyTranscript(line({ role: 'user', text: 'bye' }))
    applyTranscript(line({ role: 'marvi', id: 'seg-3', text: 'Goodbye.' }))

    clearTranscript()

    expect($heard.get()).toBeNull()
    expect($spoken.get()).toBeNull()
  })
})
