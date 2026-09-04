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
const titleBar = readFileSync(join(__dirname, 'components/TitleBar.tsx'), 'utf8')
const preload = readFileSync(join(__dirname, '../../preload/index.ts'), 'utf8')
const contextMenu = readFileSync(join(__dirname, 'components/ui/shell-context-menu.tsx'), 'utf8')
const controlSurface = readFileSync(join(__dirname, 'components/control-surface.tsx'), 'utf8')

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

  it('organises Overview as an authoritative brief with compact divided sections', () => {
    expect(app).toContain('aria-label="Current state"')
    expect(app).toContain('className="overview-runtime-facts"')
    expect(app).toContain('title="Voice route"')
    expect(app).toContain('title="Systems"')
    expect(app).toContain('title="Context"')
    expect(controlSurface).toContain('className="control-row"')
    expect(lastBlock('.control-page')).toContain('width: min(880px, 100%)')
  })

  it('uses a real collapse glyph and compositor view transition', () => {
    expect(app).toContain('document.startViewTransition')
    expect(titleBar).toContain('sidebarCollapsed ?')
    expect(app).not.toContain("collapsed ? '[>]' : '[<]'")
    expect(css).toContain('view-transition-name: marvi-sidebar')
  })

  it('keeps Marvi visible in the compact rail and provides contextual help', () => {
    expect(css).toContain('.sidebar.collapsed .brand-icon-sidebar')
    const compactLogoRule = css.slice(css.lastIndexOf('.sidebar.collapsed .brand-icon-sidebar'))
    expect(compactLogoRule.slice(0, compactLogoRule.indexOf('}'))).toContain('display: block')
    expect(app).toContain('<TooltipProvider>')
    expect(titleBar).toContain("sidebarCollapsed ? 'Show sidebar' : 'Hide sidebar'")
    expect(css).toContain('.ui-tooltip')
    expect(lastBlock('.brand-block')).toContain('height: 58px')
    expect(lastBlock('.brand-copy small')).toContain('display: block')
    expect(lastBlock('.nav-item.active')).toContain('var(--ui-accent) 8%')
    expect(lastBlock('.nav-code')).toContain('display: block')
    expect(lastBlock('.sidebar nav')).toContain('overflow-y: auto')
  })

  it('gives secondary pages a compact divided hierarchy', () => {
    expect(app).toContain('<ControlPage')
    expect(app).toContain('<ControlSection')
    expect(css).toContain('.control-section-head')
    expect(css).toContain('.control-row:first-child')
    expect(css).toContain('.settings-frame')
  })

  it('organises settings with the overlay and row grammar', () => {
    expect(app).toContain('className="settings-close"')
    expect(app).toContain("'settings-group has-gap'")
    expect(app).not.toContain('<h2>{group.label}</h2>')
    expect(css).toContain('container-name: settings-content')
    expect(css).toContain('@container settings-content (max-width: 620px)')
    expect(app).toContain("'Speech recognition'")
    expect(app).toContain("'Voice synthesis'")
    expect(app).toContain("'Wake word'")
    expect(app).toContain("'Appearance'")
    expect(app).toContain("'Themes'")
    expect(app).toContain("'Fonts'")
    expect(app).toContain("'Dynamic Island'")
    expect(app).toContain("'Desktop companion'")
    expect(app).toContain('className="settings-nav-family"')
    expect(app).toContain('className="settings-subnav"')
    expect(app).toContain('aria-expanded={voiceOpen}')
    expect(app).toContain('aria-expanded={appearanceOpen}')
    expect(app).not.toContain("page === 'Speech'")
    expect(app).toContain('title="Speech to text · STT"')
    expect(app).toContain('title="Text to speech · TTS"')
    expect(app).toContain('page?.engines ?? []')
    expect(app).toContain('[page.engineSetting]: next')
    expect(app).toContain('[page.setting]: engine?.defaultVoice')
    // Renamed from "Recognition accuracy": the row sets the chunk as well as
    // the lookahead now, and what it changes is when a word appears on screen,
    // not how accurate the recogniser is. Measured, the two move together --
    // 4,115ms and 71% clean turns against 1,868ms and 58%.
    expect(app).toContain('title="Subtitle speed"')
    expect(app).toContain('title="Window translucency"')
    expect(app).toContain('title="Alignment"')
  })

  it('uses the same working recogniser picker on Voice and in Settings', () => {
    // The Voice rig passes `compact` to drop the refresh button its tight
    // dt/dd strip has no room for -- see `.voice-hud-rig` -- but it is still
    // the one component doing the picking in both places.
    expect(app.match(/<RecogniserPicker(?: compact)? \/>/g)).toHaveLength(2)
    expect(app).not.toContain("runtime.model?.stt || 'not installed'")
    expect(app).toContain('onChange={(next) => void chooseRecogniser(next)}')
  })

  it('separates Room and Vision with the smart room hierarchy', () => {
    expect(app).toContain('<RoomPanel runtime={runtime} view="room" />')
    expect(app).toContain('<RoomPanel runtime={runtime} view="vision" />')
    expect(app).toContain('title="Live room"')
    expect(app).toContain('id="room-light-title">Light control')
    expect(app).toContain('aria-label="Light white temperature"')
    expect(app).toContain('aria-label="Custom light color"')
    expect(app).toContain('title="Devices and presence"')
    expect(app).toContain('className="vision-signal-board"')
    expect(app).not.toContain('getRoomVisionPreview')
    expect(app).toContain('title="Live perception"')
    expect(app).toContain('title="Face identity"')
    expect(app).toContain('className="face-review-item"')
    expect(css).toContain('container-name: room-page')
    expect(css).toContain('@container room-page (max-width: 720px)')
  })

  it('offers the review queue the answer it already has', () => {
    // The card showed "34% nearest match" against an empty name box -- 34% of
    // whom? The only action it invited was typing a name the library already
    // held. Measured on the live queue: forty faces, every one of them below
    // the match threshold, and nothing on screen said who they were near.
    expect(app).toContain('`Looks like ${sighting.nearest.name}`')
    expect(app).toContain('value={visitorNames[sighting.id] ?? sighting.nearest?.name')
    expect(app).toContain("'new face'")
  })

  it('can mark a reviewed face as the owner, and empty the queue at once', () => {
    // Accepting through this card always stored an ordinary visitor, so the
    // one person the room exists for was never the owner: `owner_visible`
    // stayed false and the owner threshold never fired.
    expect(app).toContain('Set as owner')
    expect(app).toContain("action: 'set_owner'")
    // Forty crops that should never have been queued is not forty decisions.
    expect(app).toContain('Reject all')
    expect(app).toContain("action: 'reject_all'")
  })

  it('keeps one window-wide status bar below both sidebars and page content', () => {
    expect(lastBlock('.app-shell')).toContain('34px minmax(0, 1fr) 24px')
    expect(app).toMatch(/<\/div>\s*\{statusbar}\s*\{settings \? \(/)
    expect(chat).not.toContain('statusbar: ReactNode')
    expect(chat).not.toContain('{statusbar}')
  })

  it('keeps compact status meters neutral instead of tinting their cells', () => {
    expect(lastBlock('.voice-level-meter')).toContain('color: var(--ui-text-tertiary)')
    expect(lastBlock('.status-context-meter')).toContain('color: var(--ui-text-tertiary)')
    expect(app).toContain('className="voice-level-meter"')
  })

  it('uses health dots and keeps camera and microphone controls out of the status bar', () => {
    const statusbar = app.slice(
      app.indexOf('const statusbar = ('),
      app.indexOf('return (', app.indexOf('const statusbar = ('))
    )
    expect(statusbar).toContain('<StatusHealthItem')
    expect(statusbar).toContain('label="Gateway"')
    expect(statusbar).toContain('label="RTC"')
    expect(statusbar).toContain('label="Voice"')
    expect(statusbar).toContain('icon={Server}')
    expect(statusbar).toContain('icon={Radio}')
    expect(statusbar).toContain('icon={Waves}')
    expect(statusbar).not.toContain('Open microphone and camera settings')
    expect(statusbar).not.toContain('<Camera')
    expect(statusbar).not.toContain('<Mic')
    expect(lastBlock('.statusbar')).toContain('overflow: visible')
    expect(lastBlock('.statusbar-side-right')).toContain('overflow: visible')
    expect(statusbar).toContain('className="status-health-cluster"')
    expect(app).toContain('role="meter"')
  })

  it('organizes Overview as a runtime brief, route, and balanced operational workspace', () => {
    expect(app).toContain('className={`overview-runtime tone-${runtimeTone}`}')
    expect(app).toContain('className="overview-runtime-facts"')
    expect(app).toContain('className="overview-workspace"')
    expect(app).toContain('className="overview-system-list"')
    expect(app).toContain('className="overview-context-list"')
    expect(lastBlock('.overview-workspace')).toContain('grid-template-columns: minmax(0, 1.35fr)')
  })

  it('moves maintenance commands into compact sidebar terminal actions', () => {
    expect(app).not.toContain('function MaintenancePanel')
    expect(app).not.toContain('LOCAL / READY')
    expect(app).toContain('className="sidebar-tools"')
    expect(app).toContain('void openMaintenanceTerminal(action)')
    expect(app).toContain('maintenancePending === action')
    expect(app).toContain('sidebar-tools-error')
    expect(lastBlock('.sidebar-tools')).toContain('grid-template-columns: repeat(4, 24px)')
  })

  it('renders confirmation modes as two distinct colored status icons', () => {
    expect(app).toContain('<ShieldOff aria-hidden="true" className="status-mode-icon is-yolo" />')
    expect(app).toContain(
      '<CheckCircle2 aria-hidden="true" className="status-mode-icon is-confirm" />'
    )
    expect(app).toContain("aria-label={`${voice.yolo ? 'YOLO' : 'Confirm'} mode`}")
    expect(lastBlock('.status-mode-icon.is-confirm')).toContain('color: #4daa72')
    expect(lastBlock('.status-mode-icon.is-yolo')).toContain('color: var(--ui-danger)')
  })

  it('routes right-click actions to the surface that owns them', () => {
    expect(contextMenu).toContain("'[data-shell-context]'")
    expect(app).toContain('actions={contextActions}')
    expect(app).toContain("surface === 'sidebar'")
    expect(app).toContain("surface === 'statusbar'")
    expect(app).toContain("surface === 'settings'")
    expect(app).toContain("surface === 'titlebar'")
    expect(app).toContain('data-shell-context="page"')
    expect(app).toContain('data-shell-context="sidebar"')
    expect(app).toContain('data-shell-context="statusbar"')
  })

  it('puts guarded whole-product lifecycle controls in the title bar', () => {
    expect(titleBar).toContain('GuardedLifecycleButton')
    expect(titleBar).toContain('Restart Marvi and all services')
    expect(titleBar).toContain('Shut down Marvi and all services')
    expect(titleBar).toContain('Press again to')
    expect(app).toContain('onRestart={() => void window.marvi?.restartAll()}')
    expect(app).toContain('onShutdown={() => void window.marvi?.shutdownAll()}')
    expect(preload).toContain("ipcRenderer.invoke('marvi:restart-all')")
    expect(preload).toContain("ipcRenderer.invoke('marvi:shutdown-all')")
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

describe('capabilities', () => {
  const panel = readFileSync(join(__dirname, 'components/connectors/ConnectorsPanel.tsx'), 'utf8')
  const catalog = readFileSync(join(__dirname, 'lib/connectors/connectorCatalog.ts'), 'utf8')

  it('offers somewhere to put the Composio key, not just the diagnosis', () => {
    // Deleting the old Accounts panel took the only field for the key with
    // it, so the page reported "not configured" and gave nowhere to fix it.
    expect(panel).toContain('aria-label="Composio API key"')
    expect(panel).toContain('configureAccounts')
    expect(panel).toContain('type="password"')
  })

  it('gives every connector its own colour behind the monogram', () => {
    // No logos: the CSP is `img-src 'self' data:`, so a logo CDN is blocked
    // and real brand marks need a dependency or vendored path data. Thirty-one
    // identical grey squares read as nothing.
    expect(catalog).toContain('tint: string')
    expect(catalog.match(/tint: '#/g)?.length).toBe(32)
  })
})

describe('connector logos', () => {
  const logos = readFileSync(join(__dirname, 'lib/connectors/connectorLogos.ts'), 'utf8')
  const catalog = readFileSync(join(__dirname, 'lib/connectors/connectorCatalog.ts'), 'utf8')
  const card = readFileSync(join(__dirname, 'components/connectors/ConnectorCard.tsx'), 'utf8')

  it('imports one icon at a time, never the package index', () => {
    // The barrel is 405 KB of 6,511 icons; `@thesvg/react/gmail` is about 2 KB.
    expect(logos).not.toMatch(/from '@thesvg\/react'/)
    expect(logos.match(/from '@thesvg\/react\/[a-z0-9-]+'/g)?.length).toBe(32)
  })

  it('has a mark for every connector in the catalog', () => {
    const slugs = [...catalog.matchAll(/slug: '([a-z0-9_]+)'/g)].map((m) => m[1])
    const mapped = new Set([...logos.matchAll(/^ {2}([a-z0-9_]+):/gm)].map((m) => m[1]))
    expect(slugs.length).toBeGreaterThan(0)
    expect(slugs.filter((slug) => !mapped.has(slug))).toEqual([])
  })

  it('uses the same mark in the modal as on the card', () => {
    // The modal was left on the monogram, so opening a connector replaced its
    // logo with two grey letters exactly when the user was looking hardest.
    const modal = readFileSync(
      join(__dirname, 'components/connectors/ConnectorConnectModal.tsx'),
      'utf8'
    )
    expect(modal).toContain('CONNECTOR_LOGOS[meta.slug]')
    expect(modal).toContain('<Logo ')
  })

  it('spells every slug the way Composio does', () => {
    // The slug is the join key against `GET /connectors` and Composio itself.
    // `onedrive` 404s there; the toolkit is `one_drive`. Checked against the
    // live API on 2026-08-28.
    expect(catalog).toContain("slug: 'one_drive'")
    expect(catalog).not.toContain("slug: 'onedrive'")
    expect(catalog).toContain("slug: 'youtube'")
  })

  it('never reaches for a remote image, because the CSP forbids it', () => {
    // `img-src 'self' data:`. Inline SVG is markup, so the policy does not
    // apply; an <img src> pointing at a logo CDN would simply not render.
    expect(card).not.toContain('src=')
    expect(card).toContain('<Logo ')
  })
})

describe('service logos', () => {
  const logos = readFileSync(join(__dirname, 'lib/serviceLogos.tsx'), 'utf8')
  const app = readFileSync(join(__dirname, 'App.tsx'), 'utf8')
  const usage = readFileSync(join(__dirname, 'components/usage-panel.tsx'), 'utf8')

  it('uses tree-shakeable TheSVG imports for external service identities', () => {
    expect(logos).not.toMatch(/from '@thesvg\/react'/)
    expect(logos.match(/from '@thesvg\/react\/[a-z0-9-]+'/g)?.length).toBe(11)
    for (const provider of [
      'anthropic',
      'claude-code',
      'codex',
      'deepinfra',
      'deepseek',
      'llamacpp',
      'lmstudio',
      'ollama',
      'openai',
      'openai-responses',
      'opencode-go',
      'opencode-zen',
      'openrouter'
    ]) {
      expect(logos).toContain(`${provider.includes('-') ? `'${provider}'` : provider}:`)
    }
  })

  it('shows the same service marks on provider setup and usage', () => {
    expect(app).toContain('<ServiceLogo className="service-brand-logo"')
    expect(usage).toContain('<ServiceLogo')
  })
})

describe('memory reader', () => {
  it('can be switched off from the Memory page', () => {
    // On by default, so the toggle has to exist for anyone who wants the
    // search results raw. `reader !== false` in the normaliser means an older
    // Gateway that does not report it still shows as on, which is what it is.
    expect(app).toContain('title="Reading the memories"')
    expect(app).toContain("apply({ reader: next === 'on' })")
    expect(app).toContain("policy?.reader === false ? 'off' : 'on'")
  })
})
