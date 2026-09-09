import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ComputerIsland } from './computer-island'
import type { ComputerStatus } from '../../../shared/computer'
const status: ComputerStatus = {
  enabled: true,
  installed: true,
  state: 'running',
  active: true,
  action: 'type_text',
  driver: 'cua-driver',
  version: '0.24.0'
}
describe('computer-use Island', () => {
  it('shows active use and immediate user controls', () => {
    const html = renderToStaticMarkup(<ComputerIsland status={status} />)
    expect(html).toContain('Marvi is using the computer')
    expect(html).toContain('PRIVATE INPUT')
    expect(html).toContain('STOP')
  })
  it('distinguishes stopping from acknowledged private input', () => {
    expect(
      renderToStaticMarkup(<ComputerIsland status={{ ...status, state: 'stopping' }} />)
    ).toContain('Marvi is stopping computer use')
    const html = renderToStaticMarkup(
      <ComputerIsland status={{ ...status, state: 'private', active: false }} />
    )
    expect(html).toContain('RESUME')
    expect(html).toContain('Computer use paused')
    expect(html).not.toContain('Marvi is using the computer')
  })
})
