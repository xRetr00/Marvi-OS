import { describe, expect, it } from 'vitest'

import { transcriptMarkdown } from './transcript'
import type { ChatMessage } from './types'

describe('transcriptMarkdown', () => {
  it('exports every supported role without changing message content', () => {
    const messages: ChatMessage[] = [
      { id: 1, at: '', role: 'user', content: 'Check the room', meta: {} },
      { id: 2, at: '', role: 'assistant', content: '**Quiet.**', meta: {} },
      { id: 3, at: '', role: 'tool', content: '{"light":0}', meta: { tool: 'room_state' } }
    ]

    expect(transcriptMarkdown(messages)).toBe(
      '## You\n\nCheck the room\n\n---\n\n## Marvi\n\n**Quiet.**\n\n---\n\n## Tool · room_state\n\n{"light":0}'
    )
  })
})
