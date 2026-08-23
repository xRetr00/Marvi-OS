import { describe, expect, it } from 'vitest'

import type { ChatMessage } from './types'
import { userAncestor } from './useChat'

const message = (id: number, role: ChatMessage['role'], parentId: number | null): ChatMessage => ({
  id,
  at: '2026-08-23T00:00:00Z',
  role,
  content: role === 'user' ? 'original question' : '',
  meta: {},
  threadId: 'default',
  parentId,
  branchId: 'main',
  parts: [],
  attachments: []
})

describe('regeneration ancestry', () => {
  it('finds the user turn through intervening tool results', () => {
    const messages = [message(1, 'user', null), message(2, 'tool', 1), message(3, 'assistant', 2)]

    expect(userAncestor(messages, messages[2])?.id).toBe(1)
  })
})
