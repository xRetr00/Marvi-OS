import { beforeEach, describe, expect, it } from 'vitest'

import {
  $heard,
  $spoken,
  applyTranscript,
  clearTranscript,
  SUBTITLE_CHARS,
  subtitleTail
} from './transcript'

/**
 * Subtitles are judged on one thing: do they read as the sentence being said,
 * or as a UI arguing with itself. A recogniser revises its guess several times
 * a second, so the same segment arrives again, longer — growing in place is the
 * whole behaviour, and replacing the line instead is the stutter people notice.
 */
beforeEach(() => clearTranscript())

const line = (
  over: Partial<Parameters<typeof applyTranscript>[0]> = {}
): Parameters<typeof applyTranscript>[0] => ({
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

describe('a subtitle is a glance, not a transcript', () => {
  it('keeps a short line exactly as it is', () => {
    expect(subtitleTail('Turning the light on.')).toBe('Turning the light on.')
  })

  it('shows the tail of a long one, not the head', () => {
    // Live text: the words being said right now are the ones worth reading,
    // and clamping from the top would show the opening of an answer that has
    // long since moved on.
    const long = `${'word '.repeat(200)}the final words here`
    const shown = subtitleTail(long)

    expect(shown).toContain('the final words here')
    expect(shown.length).toBeLessThanOrEqual(SUBTITLE_CHARS + 4)
  })

  it('starts at a sentence, not wherever the budget ran out', () => {
    // What was on screen: "… running perfectly. Presence is detected via the
    // sensor…" -- a fragment of a sentence whose start nobody can see, which
    // reads as damage rather than as a caption.
    const reply =
      'I went through every service just now and all of them came back healthy. ' +
      'Presence is detected via the sensor, and the light and the camera are both confirmed working.'
    const shown = subtitleTail(reply)

    expect(shown).toBe(
      'Presence is detected via the sensor, and the light and the camera are both confirmed working.'
    )
    expect(shown.startsWith('…')).toBe(false)
  })

  it('fills the rest of the budget with whole sentences and no half ones', () => {
    const shown = subtitleTail(`${'Said before. '.repeat(30)}This last one is being said now.`)

    expect(shown.endsWith('This last one is being said now.')).toBe(true)
    expect(shown.startsWith('Said before.')).toBe(true)
    expect(shown.length).toBeLessThanOrEqual(SUBTITLE_CHARS)
  })

  it('marks a cut when one sentence is longer than the whole budget', () => {
    expect(subtitleTail('x '.repeat(400))).toMatch(/^…/)
  })

  it('collapses the newlines that filled the window', () => {
    // A long answer wrapped line after line until it covered the orb it was
    // meant to caption.
    expect(subtitleTail('one\n\ntwo   three\n')).toBe('one two three')
  })
})
