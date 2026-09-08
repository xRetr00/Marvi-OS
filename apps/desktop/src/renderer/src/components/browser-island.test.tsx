import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { BrowserIsland } from './browser-island'

describe('browser handoff', () => {
  it('offers explicit resume without exposing page observations during private entry', () => {
    const html = renderToStaticMarkup(
      <BrowserIsland
        session={{
          id: 'fixture',
          profile_id: 'default',
          objective: 'Browse',
          revision: 1,
          state: 'private',
          detail: 'Private input',
          tabs: [{ id: 'tab', url: 'https://secret.example' }]
        }}
      />
    )
    expect(html).toContain('PRIVATE INPUT · PAUSED')
    expect(html).toContain('RESUME')
    expect(html).not.toContain('secret.example')
  })
  it('keeps stopping explicit and disables another stop', () => {
    const html = renderToStaticMarkup(
      <BrowserIsland
        session={{
          id: 'fixture',
          profile_id: 'default',
          objective: 'Browse',
          revision: 2,
          state: 'stopping',
          detail: 'Stopping automation; please wait before typing.',
          tabs: []
        }}
      />
    )
    expect(html).toContain('please wait before typing')
    expect(html).toContain('disabled=""')
    expect(html).not.toContain('RESUME')
  })
})
