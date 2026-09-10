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
const ui = readFileSync(join(__dirname, 'ask.css'), 'utf8')

describe('the transcript keeps the structure chat.css styles', () => {
  it('puts the scroller inside the positioned viewport', () => {
    expect(html).toMatch(/class="chat-thread-viewport"[^>]*>[\s\S]*?class="chat-log"/)
  })

  it('renders the column wrapper that every turn sits in', () => {
    expect(html).toContain('chat-thread-content')
    // It uses the page now -- the 720px cap left a wide window mostly empty
    // and gave a right-aligned bubble nowhere to go.
    expect(ui).toMatch(/\.chat-thread-content\s*\{[^}]*max-width:\s*none/)
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
    expect(html).toMatch(
      /class="chat-compose-row"><div class="chat-compose-leading">[\s\S]*?<textarea/
    )
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

describe('the user turn is a bubble, not a card', () => {
  it('lays the turn out in two columns so the bubble can sit right', () => {
    expect(ui).toMatch(
      /\.chat-user\s*\{[^}]*grid-template-columns:\s*minmax\(56px,\s*1fr\)\s*minmax\(0,\s*62%\)/
    )
  })

  it('lets the bubble size to its own text', () => {
    expect(ui).toMatch(/\.chat-user-surface\s*\{[^}]*width:\s*auto/)
    expect(ui).toMatch(/\.chat-user-surface\s*\{[^}]*grid-column:\s*2/)
  })

  it('drops the clamp that hid the end of a long message', () => {
    expect(ui).toMatch(/\.chat-user-text\s*\{[^}]*max-height:\s*none/)
  })

  it('keeps the action row inside the bubble', () => {
    // Floating it into the empty column left the controls stranded away from
    // the message they act on.
    expect(ui).toMatch(/\.chat-user-actions\s*\{[^}]*justify-content:\s*flex-end/)
    // Collapsed, not just transparent: a transparent row still reserves an
    // empty band under every bubble.
    expect(ui).toMatch(/\.chat-user-actions\s*\{[^}]*max-height:\s*0/)
  })
})

describe('what Marvi thought is readable', () => {
  it('runs at prose size rather than as a 9px field', () => {
    expect(ui).toMatch(/\.chat-reasoning-body\s*\{[^}]*font-size:\s*11px/)
  })

  it('fades instead of showing a scrollbar while it is being written', () => {
    expect(ui).toMatch(/\.chat-reasoning-body\.is-live\s*\{[^}]*mask-image/)
  })
})

describe('the stop control is not the loudest thing on the page', () => {
  it('is outlined rather than a filled disc', () => {
    expect(ui).toMatch(/\.chat-send\.is-stop\s*\{[^}]*background:\s*transparent/)
  })
})

describe('the live activity line stays quieter than the answer', () => {
  it('is small and light, not body-weight text', () => {
    expect(ui).toMatch(/\.chat-scaffold-label\s*\{[^}]*font-size:\s*11px/)
    expect(ui).toMatch(/\.chat-scaffold-label\s*\{[^}]*font-weight:\s*400/)
  })

  it('shimmers rather than flashing the whole line', () => {
    expect(ui).toMatch(/\.chat-scaffold-label\.is-live\s*\{[^}]*background-clip:\s*text/)
    expect(ui).toContain('@keyframes chat-shimmer')
  })

  it('drops the animation entirely for reduced motion', () => {
    expect(ui).toMatch(/prefers-reduced-motion[\s\S]*?animation:\s*none/)
  })

  it('carries no spinner and no scrambling text', () => {
    expect(ui).not.toContain('chat-ascii')
    expect(html).not.toContain('esc to interrupt')
  })
})

describe('the bubble hugs its text', () => {
  it('does not stretch to fill its grid track', () => {
    // A grid item stretches by default, which turns the bubble back into a bar.
    expect(ui).toMatch(/\.chat-user-surface\s*\{[^}]*justify-self:\s*end/)
  })
})

describe('copying goes through the main process', () => {
  it('does not use the SDK copy primitive', () => {
    // `ActionBarPrimitive.Copy` calls `navigator.clipboard`, which needs a
    // secure context and a focused document. In this window it rejects, and
    // the button silently does nothing.
    const messages = readFileSync(join(__dirname, 'Messages.tsx'), 'utf8')
    expect(messages).not.toContain('ActionBarPrimitive.Copy')
    expect(messages).toContain('CopyMessageAction')
  })

  it('reaches Electron’s clipboard, with a browser fallback', () => {
    const action = readFileSync(join(__dirname, '..', 'components', 'MessageAction.tsx'), 'utf8')
    expect(action).toContain('window.marvi?.copyText')
    expect(action).toContain('navigator.clipboard.writeText')
  })
})
