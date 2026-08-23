import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { OFFLINE_RUNTIME, deviceLabel, deviceState } from '../../shared/runtime'

/**
 * The shell layout, and the honesty of what it reports.
 *
 * Both were reported as "the UI is broken", and both had the same shape: the
 * app was confidently displaying something that was not true — content that
 * existed but could not be reached, and devices that were reported on without
 * anything having looked.
 */

// Normalised: the repo checks out CRLF on Windows, and a test that greps for
// `\n.selector {` finds nothing there for a reason that has nothing to do with
// what it is testing.
const css = readFileSync(join(__dirname, 'assets/main.css'), 'utf8').replace(/\r\n/g, '\n')
const voiceOrb = readFileSync(join(__dirname, 'orb/VoiceOrb.tsx'), 'utf8')
const app = readFileSync(join(__dirname, 'App.tsx'), 'utf8')
const chat = readFileSync(join(__dirname, 'chat/Chat.tsx'), 'utf8')

/** The rule block for a selector, so a moved property still fails the test. */
function block(selector: string): string {
  const at = css.indexOf(`\n${selector} {`)
  if (at === -1) throw new Error(`no rule for ${selector}`)
  return css.slice(at, css.indexOf('}', at))
}

function lastBlock(selector: string): string {
  const at = css.lastIndexOf(`\n${selector} {`)
  if (at === -1) throw new Error(`no rule for ${selector}`)
  return css.slice(at, css.indexOf('}', at))
}

describe('shell layout', () => {
  it('lets the sidebar and content be the size of their grid track', () => {
    // A grid item defaults to `min-height: auto` — "never smaller than my
    // content". Without this, a page taller than the window pushed both past
    // the shell, `body { overflow: hidden }` clipped the excess, and the status
    // bar and the bottom of every long page were unreachable.
    expect(block('.sidebar,\n.content')).toContain('min-height: 0')
  })

  it('gives the page one scroll container', () => {
    const rule = block('.page-scroll')
    expect(rule).toContain('overflow-y: auto')
    // Without this the container inherits the same auto minimum it exists to fix.
    expect(rule).toContain('min-height: 0')
  })

  it('lets a short page fill the space and a long one scroll', () => {
    expect(block('.page-scroll > *')).toContain('min-height: 100%')
  })

  it('scrolls the sidebar, which has more destinations than a laptop has height', () => {
    expect(block('.sidebar nav')).toContain('overflow-y: auto')
  })

  it('draws a scrollbar that is visible before you gesture at it', () => {
    // An overlay scrollbar that appears only mid-scroll is indistinguishable
    // from no scrollbar, which is how a clipped page reads as a broken one.
    expect(css).toContain('::-webkit-scrollbar')
    expect(block('::-webkit-scrollbar-thumb')).toContain('background:')
  })

  it('has no fixed-width ascii divider left', () => {
    // `+------------------------------+` was 32 characters wide whatever the
    // panel was, so it read as a stray box; two around an empty section looked
    // like a maze.
    expect(css).not.toContain('ascii-divider')
    expect(block('.ascii-rule-fill')).toContain('overflow: hidden')
  })

  it('keeps the voice orb audio-driven instead of pointer-driven', () => {
    expect(css).not.toContain('cursor: crosshair')
    expect(voiceOrb).not.toContain('pointermove')
    expect(voiceOrb).not.toContain('PointerEvent')
  })

  it('puts updates in About instead of a second settings destination', () => {
    expect(app).not.toContain("'Maintenance', 'Updates', 'About'")
    expect(app).toContain('<AboutUpdates version={build.version} />')
    expect(app).not.toContain('about-provenance')
  })

  it('organises Overview as four labelled dashboard modules', () => {
    expect(app).toContain('overview-dashboard')
    expect(app).toContain('CURRENT STATE')
    expect(app).toContain('VOICE PATH')
    expect(app).toContain('SERVICE HEALTH')
    expect(app).toContain('CONTEXT')
    expect(css).toContain('grid-template-columns: repeat(12, minmax(0, 1fr))')
  })

  it('uses a real collapse glyph and compositor view transition', () => {
    expect(app).toContain('document.startViewTransition')
    expect(app).toContain('aria-pressed={collapsed}')
    expect(app).not.toContain("collapsed ? '[>]' : '[<]'")
    expect(css).toContain('view-transition-name: marvi-sidebar')
  })

  it('keeps Marvi visible in the compact rail and provides contextual help', () => {
    expect(css).toContain('.sidebar.collapsed .brand-icon-sidebar')
    const compactLogoRule = css.slice(css.lastIndexOf('.sidebar.collapsed .brand-icon-sidebar'))
    expect(compactLogoRule.slice(0, compactLogoRule.indexOf('}'))).toContain('display: block')
    expect(app).toContain('<TooltipProvider>')
    expect(app).toContain("label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}")
    expect(css).toContain('.ui-tooltip')
  })

  it('gives secondary pages a bounded module hierarchy', () => {
    expect(css).toContain("content: '+  ACTIVE MODULE'")
    expect(css).toContain('.page-lead-module')
    expect(css).toContain('.single-page.panel > .service-list')
  })

  it('keeps one window-wide status bar below both sidebars and page content', () => {
    expect(lastBlock('.app-shell')).toContain('34px minmax(0, 1fr) 20px')
    expect(app).toMatch(/<\/div>\s*\{statusbar}\s*\{settings \? \(/)
    expect(chat).not.toContain('statusbar: ReactNode')
    expect(chat).not.toContain('{statusbar}')
  })

  it('retains the blue live voice meter inside the Hermes chrome', () => {
    expect(lastBlock('.voice-level-meter')).toContain('color: var(--ui-accent)')
    expect(app).toContain("value > 0.02 ? ' is-live' : ''")
  })
})

describe('what the shell claims about the devices', () => {
  it('says nothing it cannot know when Marvi is unreachable', () => {
    // The regression: `microphone: true` and `camera: true` were defaults that
    // nothing ever assigned, so the status bar read "MIC ON / CAM ON" with the
    // Gateway offline. This is the one indicator a user checks to find out
    // whether they are being listened to.
    expect(deviceState(OFFLINE_RUNTIME, 'microphone')).toBe('unknown')
    expect(deviceState(OFFLINE_RUNTIME, 'camera')).toBe('unknown')
    expect(deviceLabel('unknown')).toBe('?')
  })

  it('reports a device on only when the component that owns it is ready', () => {
    const running = {
      state: 'ready' as const,
      components: {
        voice: { state: 'ready' as const, detail: '' },
        vision: { state: 'pending' as const, detail: 'enable Smart Room vision' }
      }
    }
    expect(deviceState(running, 'microphone')).toBe('on')
    expect(deviceState(running, 'camera')).toBe('off')
  })

  it('does not claim the assistant is ready when nothing has answered', () => {
    // OFFLINE_RUNTIME reused the ready-state default, so an unreachable Marvi
    // said "Say Marvi" and the status bar said VOICE READY.
    expect(OFFLINE_RUNTIME.assistant.phase).toBe('error')
    expect(OFFLINE_RUNTIME.assistant.level).toBe(0)
  })
})
