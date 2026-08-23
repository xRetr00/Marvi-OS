import { describe, expect, it } from 'vitest'

import { transcriptMarkdown } from './transcript'
import type { ChatMessage } from './types'

describe('transcriptMarkdown', () => {
  it('exports every supported role without changing message content', () => {
    const messages: ChatMessage[] = [
      message(1, 'user', 'Check the room'),
      message(2, 'assistant', '**Quiet.**'),
      message(3, 'tool', '{"light":0}', { tool: 'room_state' })
    ]

    expect(transcriptMarkdown(messages)).toBe(
      '## You\n\nCheck the room\n\n---\n\n## Marvi\n\n**Quiet.**\n\n---\n\n## Tool · room_state\n\n{"light":0}'
    )
  })
})

function message(
  id: number,
  role: ChatMessage['role'],
  content: string,
  meta: Record<string, unknown> = {}
): ChatMessage {
  return {
    id,
    at: '',
    role,
    content,
    meta,
    threadId: 'default',
    parentId: null,
    branchId: 'main',
    parts: [{ type: 'text', text: content }],
    attachments: []
  }
}
