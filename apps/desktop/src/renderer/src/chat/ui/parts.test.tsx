import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { MESSAGE_PART_COMPONENTS } from './parts'

/**
 * The bug: a turn that finished on a widget or a tool card said "Marvi is
 * working" forever, including after the next turn had started.
 *
 * The SDK renders the Empty slot whenever a message *ends* on something that
 * is not text or reasoning -- which a perfectly finished reply ending on a
 * widget does. So Empty has to decide for itself whether anything is running.
 */
describe('the working indicator', () => {
  const Empty = MESSAGE_PART_COMPONENTS.Empty

  it('shows while the reply is actually running', () => {
    const html = renderToStaticMarkup(<Empty status={{ type: 'running' }} />)
    expect(html).toContain('Marvi is working')
  })

  it('renders nothing once the turn has finished', () => {
    const html = renderToStaticMarkup(<Empty status={{ type: 'complete' }} />)
    expect(html).toBe('')
  })

  it('renders nothing for a turn that ended in error or was cancelled', () => {
    expect(
      renderToStaticMarkup(<Empty status={{ type: 'incomplete', reason: 'error' }} />)
    ).toBe('')
    expect(
      renderToStaticMarkup(<Empty status={{ type: 'incomplete', reason: 'cancelled' }} />)
    ).toBe('')
  })
})
