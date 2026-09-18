import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { MeetingsPage } from './meetings-page'
import { RecordingDot } from './recording-dot'

/**
 * Rendered with no Gateway, which is what the first frame of every launch
 * looks like. Two things have to be true even then, and they are the two
 * things this feature is judged on: nothing offers to record until it knows
 * the notice was accepted, and the indicator is absent rather than guessing.
 */
const markup = renderToStaticMarkup(<MeetingsPage />)

describe('the meetings page', () => {
  it('says who starts a recording, on the page itself', () => {
    expect(markup).toContain('You start every recording; she never does.')
  })

  it('will not offer to record before it has heard from the Gateway', () => {
    // `page` is null until the first fetch returns, and the button is disabled
    // then -- a Record button that works before Marvi knows whether the
    // machine can record, or whether the notice was accepted, is a button that
    // opens a microphone on a guess.
    expect(markup).toContain('disabled=""')
  })

  it('has nothing to show and says so', () => {
    expect(markup).toContain('Nothing recorded yet.')
    expect(markup).not.toContain('undefined')
  })
})

describe('the recording indicator', () => {
  it('draws nothing at all when nothing is being recorded', () => {
    // Not a grey dot, not a placeholder: the presence of this element is the
    // signal, so it must never be present for any other reason.
    expect(renderToStaticMarkup(<RecordingDot onOpen={() => {}} />)).toBe('')
  })
})
