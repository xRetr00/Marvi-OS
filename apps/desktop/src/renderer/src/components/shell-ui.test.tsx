import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it } from 'vitest'

import { BootFailureOverlay } from './BootFailureOverlay'
import { ConnectingOverlay } from './ConnectingOverlay'
import { TitleBar } from './TitleBar'
import { GlyphSpinner } from './ui/glyph-spinner'
import { DecodeText } from './ui/decode-text'
import { OFFLINE_RUNTIME } from '../../../shared/runtime'
import { $runtimeState } from '../store/voice-state'

afterEach(() => {
  $runtimeState.set(OFFLINE_RUNTIME)
})

describe('TitleBar', () => {
  it('paints brand, current page, and the three window controls', () => {
    const html = renderToStaticMarkup(<TitleBar page="Overview" />)

    expect(html).toContain('titlebar')
    expect(html).toContain('MARVI OS')
    expect(html).toContain('OVERVIEW')
    expect(html).toContain('aria-label="Minimize"')
    expect(html).toContain('aria-label="Maximize"')
    expect(html).toContain('aria-label="Close"')
  })

  it('carries drag region styling hooks for the frameless window', () => {
    const html = renderToStaticMarkup(<TitleBar page="Voice" />)

    expect(html).toContain('class="titlebar"')
    expect(html).toContain('no-drag')
  })
})

describe('ConnectingOverlay', () => {
  it('shows the decode CONNECTING wall while the gateway is offline', () => {
    const html = renderToStaticMarkup(<ConnectingOverlay />)

    expect(html).toContain('connecting-overlay')
    // Decode effect: only the legible prefix survives the scramble mid-boot.
    expect(html).toContain('CONN')
    expect(html).toContain('MARVI GATEWAY UNAVAILABLE')
  })

  it('stays mounted through the starting state with the gateway detail', () => {
    $runtimeState.set({ ...OFFLINE_RUNTIME, state: 'starting' })
    const html = renderToStaticMarkup(<ConnectingOverlay />)

    expect(html).toContain('connecting-overlay')
    expect(html).toContain('aria-hidden="false"')
  })
})

describe('BootFailureOverlay', () => {
  it('renders nothing while the gateway is merely offline', () => {
    expect(renderToStaticMarkup(<BootFailureOverlay />)).toBe('')
  })

  it('surfaces diagnostics and recovery actions on a hard error', () => {
    $runtimeState.set({ ...OFFLINE_RUNTIME, state: 'error' })
    const html = renderToStaticMarkup(<BootFailureOverlay />)

    expect(html).toContain('BOOT FAILURE')
    expect(html).toContain('RETRY BOOT')
    expect(html).toContain('GATEWAY: OFFLINE')
    expect(html).toContain('LIVEKIT: OFFLINE')
  })
})

describe('GlyphSpinner', () => {
  it('renders the first braille frame as a live-region status', () => {
    const html = renderToStaticMarkup(<GlyphSpinner spinner="braille" />)

    expect(html).toContain('glyph-spinner')
    expect(html).toContain('role="status"')
    expect(html).toContain('⠋')
  })

  it('falls back to braille for unknown spinner names', () => {
    const html = renderToStaticMarkup(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      <GlyphSpinner spinner={'nope' as any} />
    )

    expect(html).toContain('⠋')
  })
})

describe('DecodeText', () => {
  it('renders plain text when inactive (reduced motion / exit frame)', () => {
    const html = renderToStaticMarkup(<DecodeText active={false} text="CONNECTING" />)

    expect(html).toContain('CONNECTING')
  })

  it('never scrambles the legible prefix', () => {
    const html = renderToStaticMarkup(
      <DecodeText active prefix={4} text="CONNECTING" />
    )

    expect(html).toContain('CONN')
  })
})
