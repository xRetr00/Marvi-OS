import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ContextSettings } from './context-settings'

describe('context settings while Gateway state is loading', () => {
  it('labels independent controls and disables them until authoritative settings arrive', () => {
    const html = renderToStaticMarkup(<ContextSettings />)
    for (const label of ['Room', 'Vision', 'Weather', 'Map and location', 'Memory']) {
      expect(html).toContain(`aria-label="${label}: Feed Mind"`)
      expect(html).toContain(`aria-label="${label}: Include in prompts"`)
    }
    const switches = html.match(/<button[^>]+role="switch"[^>]*>/g) ?? []
    expect(switches.length).toBeGreaterThan(10)
    expect(switches.every((button) => button.includes('disabled'))).toBe(true)
    expect(html).toContain('aria-label="Mind power"')
    expect(html).toContain('aria-label="Announcer"')
  })
})
