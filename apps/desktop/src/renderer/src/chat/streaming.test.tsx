import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { AgentMessage } from './components/AgentMessage'
import type { ChatMessage } from './types'

/**
 * The streaming render.
 *
 * A reply that stops updating looks identical to a reply that finished, and a
 * cursor left on a finished reply says the opposite. Both are silent failures,
 * so both are asserted.
 */
function reply(content: string, meta: Record<string, unknown> = {}): ChatMessage {
  return {
    id: 1,
    at: new Date().toISOString(),
    role: 'assistant',
    content,
    meta: meta as ChatMessage['meta'],
    threadId: 'default',
    parentId: null,
    branchId: 'main',
    parts: [{ type: 'text', text: content }],
    attachments: []
  }
}

const markup = (message: ChatMessage): string =>
  renderToStaticMarkup(<AgentMessage message={message} />)

describe('a streaming reply', () => {
  it('shows a timed activity row while tokens are still arriving', () => {
    const html = markup(reply('The light', { streaming: true }))
    expect(html).toContain('chat-stream-activity')
    expect(html).toContain('chat-activity-pulse')
    expect(html).toContain('Working')
  })

  it('drops live activity once the turn is over', () => {
    expect(markup(reply('The light is on.'))).not.toContain('chat-stream-activity')
  })

  it('renders whatever text has arrived so far', () => {
    expect(markup(reply('The light', { streaming: true }))).toContain('The light')
  })
})

describe('reasoning', () => {
  it('is not shown as the answer', () => {
    // The one thing that must never read as something Marvi said.
    const html = markup(reply('Yes.', { reasoning: 'the user asked about the light' }))
    const body = html.slice(html.indexOf('chat-body'))

    expect(body).toContain('Yes.')
    expect(body).not.toContain('the user asked')
  })

  it('is collapsed until asked for', () => {
    const html = markup(reply('Yes.', { reasoning: 'a long deliberation' }))

    expect(html).toContain('chat-disclosure-row')
    expect(html).not.toContain('chat-reasoning-body')
    expect(html).not.toContain('a long deliberation')
  })

  it('opens live reasoning while it is arriving and labels it as thinking', () => {
    const html = markup(reply('', { reasoning: 'checking the room state', streaming: true }))

    expect(html).toContain('aria-expanded="true"')
    expect(html).toContain('chat-reasoning-body is-live')
    expect(html).toContain('checking the room state')
    expect(html).toContain('Thinking')
    expect(html).toContain('chat-activity-time')
  })

  it('is absent entirely when the model did not reason', () => {
    expect(markup(reply('Yes.'))).not.toContain('chat-reasoning')
  })
})
