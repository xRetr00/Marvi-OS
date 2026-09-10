import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { Chat } from './Chat'

describe('chat boot', () => {
  it('renders without throwing', () => {
    const html = renderToStaticMarkup(<Chat onExit={() => {}} />)
    expect(html).toContain('chat-page')
  })
})
