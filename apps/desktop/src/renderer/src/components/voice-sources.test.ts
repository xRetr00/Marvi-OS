/**
 * Where Marvi has been, derived from what she called.
 *
 * The tool list answers "what did she do". This answers "what did she look
 * at", which is the question you ask when an answer surprises you.
 */
import { describe, expect, it } from 'vitest'

import type { VoiceCall } from './voice-cards'
import { sourcesFrom } from './voice-sources'

function call(tool: string, args: Record<string, unknown>, outcome = 'ok'): VoiceCall {
  return { id: tool, tool, arguments: args, outcome: outcome as VoiceCall['outcome'], ms: 10 }
}

describe('sources', () => {
  it('shows a page by its host, not its whole url', () => {
    const found = sourcesFrom([call('web_fetch', { url: 'https://www.livekit.io/docs/agents' })])

    expect(found[0].label).toBe('livekit.io')
    expect(found[0].kind).toBe('web')
    // The whole thing survives for the tooltip: a host is enough to recognise
    // and not enough to go back to.
    expect(found[0].full).toContain('/docs/agents')
  })

  it('shows a file by its name, on either kind of path', () => {
    const found = sourcesFrom([
      call('file_read', { path: 'D:\\Marvi-OS\\AGENTS.md' }),
      call('file_read', { path: '/home/x/notes.txt' })
    ])

    expect(found.map((source) => source.label)).toEqual(['AGENTS.md', 'notes.txt'])
    expect(found[0].kind).toBe('file')
  })

  it('counts a place touched more than once rather than listing it twice', () => {
    const found = sourcesFrom([
      call('web_fetch', { url: 'https://example.com/a' }),
      call('browser_open', { url: 'https://example.com/a' })
    ])

    expect(found).toHaveLength(1)
    expect(found[0].times).toBe(2)
  })

  it('leaves out what failed', () => {
    // She did not look at a page that did not load, and saying she did is the
    // same class of untruth as claiming a tool ran.
    const found = sourcesFrom([call('web_fetch', { url: 'https://gone.invalid' }, 'failed')])

    expect(found).toEqual([])
  })

  it('counts a search as somewhere she went', () => {
    // A deliberate stretch: "she searched for X" is the same kind of fact as
    // "she read Y", and leaving it out made the list look emptier than the
    // session was.
    const found = sourcesFrom([call('web_search', { query: 'EA Sports FC 26' })])

    expect(found[0].label).toBe('EA Sports FC 26')
  })

  it('ignores arguments that are not places', () => {
    const found = sourcesFrom([call('room_set_light', { on: true, brightness: 40 })])

    expect(found).toEqual([])
  })
})
