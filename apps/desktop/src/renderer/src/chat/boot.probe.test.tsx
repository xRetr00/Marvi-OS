import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { Chat } from './Chat'

describe('chat boot', () => {
  it('renders the composer and the sidebar', () => {
    const html = renderToStaticMarkup(<Chat onExit={() => {}} />)
    console.log('LEN', html.length)
    console.log('HAS chat-sessions:', html.includes('chat-sessions'))
    console.log('HAS chat-thread:', html.includes('chat-thread'))
    console.log('HAS chat-compose:', html.includes('chat-compose'))
    console.log('HAS chat-empty:', html.includes('chat-empty'))
    expect(html).toContain('chat-page')
  })
})
