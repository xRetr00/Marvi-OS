import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { Chat } from '../Chat'

/**
 * The transcript's structure, not its styling.
 *
 * `chat.css` styles by element structure, not by component: `chat-log` is the
 * scroller, `chat-thread-content` is the 720px centred column, and
 * `chat-scroll-bottom` positions itself against `chat-thread-viewport`. Moving
 * to the SDK's primitives kept the class names and dropped the wrappers, and
 * every message went full-bleed across the window while the composer stretched
 * with it. Nothing in a type or a snapshot catches that; this does.
 */
const html = renderToStaticMarkup(<Chat onExit={() => {}} />)
const css = readFileSync(join(__dirname, '..', 'chat.css'), 'utf8')

describe('the transcript keeps the structure chat.css styles', () => {
  it('puts the scroller inside the positioned viewport', () => {
    expect(html).toMatch(/class="chat-thread-viewport"[^>]*>[\s\S]*?class="chat-log"/)
  })

  it('renders the centred column that constrains every turn', () => {
    // Without this wrapper the turns inherit the full window width.
    expect(html).toContain('chat-thread-content')
    expect(css).toMatch(/\.chat-thread-content\s*\{[^}]*width:\s*min\(100%,\s*720px\)/)
  })

  it('keeps the composer out of the scroll viewport', () => {
    const log = html.indexOf('chat-log')
    const compose = html.indexOf('chat-compose')
    const content = html.indexOf('chat-thread-content')
    expect(compose).toBeGreaterThan(-1)
    // The composer is a sibling of the viewport in chat-main, so it appears
    // after the thread content rather than nested inside it.
    expect(compose).toBeGreaterThan(content)
    expect(log).toBeLessThan(compose)
  })

  it('gives the composer the grid its rules target', () => {
    expect(html).toContain('chat-compose-field')
    expect(html).toContain('chat-compose-row')
    expect(html).toContain('chat-compose-leading')
    expect(html).toContain('chat-compose-controls')
    // `grid-area: input` only applies to a direct child of the row.
    expect(html).toMatch(/class="chat-compose-row"><div class="chat-compose-leading">[\s\S]*?<textarea/)
  })

  it('anchors the scroll-to-bottom button, and hides it at the bottom', () => {
    expect(html).toContain('chat-scroll-bottom')
    expect(css).toMatch(/\.chat-scroll-bottom\s*\{[^}]*position:\s*absolute/)
  })

  it('uses the starter markup the empty state is styled for', () => {
    expect(html).toContain('chat-empty')
    expect(html).toContain('chat-empty-mark')
    expect(html).toContain('chat-starters')
    expect(html).toContain('chat-empty-logo')
  })
})
