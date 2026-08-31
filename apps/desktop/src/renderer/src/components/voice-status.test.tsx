/**
 * The status, in the page header.
 *
 * The header used to spend its slot on a hardcoded `READY / Say Marvi` — the
 * phase and a caption, saying nothing the state could not say for itself —
 * while the real panel floated over the field competing with the orb.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { AssistantState } from '../../../shared/runtime'
import { VoiceStatus } from './voice-status'

const ready = { phase: 'ready', caption: 'Say Marvi', detail: null } as unknown as AssistantState
const listening = {
  phase: 'listening',
  caption: 'Listening',
  detail: null
} as unknown as AssistantState

describe('the header status', () => {
  it('does not claim to be listening before the session is joined', () => {
    // Saying READY for a page nobody had joined was a lie: it claimed Marvi
    // was listening while nothing was in the room.
    const html = renderToStaticMarkup(<VoiceStatus link="idle" voice={ready} warming={false} />)

    expect(html).toContain('IDLE')
    expect(html).toContain('Press Join to start listening')
    expect(html).not.toContain('READY')
  })

  it('says the models are still loading', () => {
    // Joining before they finish produced a session that showed LISTENING and
    // heard nothing — you could talk into it for as long as you liked.
    const html = renderToStaticMarkup(<VoiceStatus link="live" voice={listening} warming={true} />)

    expect(html).toContain('WARMING UP')
    expect(html).toContain('Loading the speech models')
  })

  it('shows the phase once the session is live', () => {
    const html = renderToStaticMarkup(<VoiceStatus link="live" voice={listening} warming={false} />)

    expect(html).toContain('LISTENING')
    expect(html).toContain('phase-listening')
  })

  it('carries the reason nothing is working, and only when there is one', () => {
    const withBlocker = renderToStaticMarkup(
      <VoiceStatus blocker="Gateway unreachable" link="idle" voice={ready} warming={false} />
    )
    const without = renderToStaticMarkup(
      <VoiceStatus blocker="" link="idle" voice={ready} warming={false} />
    )

    expect(withBlocker).toContain('Gateway unreachable')
    // A permanent empty slot in a header is furniture.
    expect(without).not.toContain('voice-status-blocker')
  })
})
