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

/**
 * The message design, asserted where it is actually decided.
 *
 * The turn layout moved out of `chat.css` and into `ask.css` deliberately, so
 * the contract moved with it. A user turn that is not a two-column grid is a
 * full-width card again, which is the thing this whole section exists to stop.
 */
const ui = readFileSync(join(__dirname, 'ask.css'), 'utf8')

describe('the user turn is a bubble, not a card', () => {
  it('lays the turn out in two columns so the bubble can sit right', () => {
    expect(ui).toMatch(
      /\.chat-user\s*\{[^}]*grid-template-columns:\s*minmax\(56px,\s*1fr\)\s*minmax\(0,\s*80%\)/
    )
  })

  it('lets the bubble size to its own text', () => {
    expect(ui).toMatch(/\.chat-user-surface\s*\{[^}]*width:\s*auto/)
    expect(ui).toMatch(/\.chat-user-surface\s*\{[^}]*grid-column:\s*2/)
  })

  it('drops the clamp that hid the end of a long message', () => {
    expect(ui).toMatch(/\.chat-user-text\s*\{[^}]*max-height:\s*none/)
  })

  it('places the action row and branch picker in their own cells', () => {
    // The fixture thread is empty, so this asserts the placement rules rather
    // than the markup: a user turn only exists once there is a message.
    expect(ui).toMatch(/\.chat-user-actions\s*\{[^}]*grid-column:\s*1/)
    expect(ui).toMatch(/\.chat-user-branches\s*\{[^}]*justify-self:\s*end/)
  })
})
