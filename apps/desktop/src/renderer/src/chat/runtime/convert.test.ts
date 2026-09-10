/**
 * The seam the SDK refactor rests on.
 *
 * Every message the window draws goes through `convertMessage`, so a mapping
 * bug here is invisible until something renders wrong on screen. It is a pure
 * function over two wire formats, which makes it the cheapest place in the
 * whole change to be certain about.
 */

import { describe, expect, it } from 'vitest'

import type { ChatMessage } from '../types'
import { ASK_TOOL, WIDGET_TOOL, convertMessage, convertMessages, isRenderable } from './convert'

const at = '2026-08-17T14:05:00Z'

function message(overrides: Partial<ChatMessage>): ChatMessage {
  return {
    id: 1,
    at,
    role: 'user',
    content: 'hi',
    meta: {},
    threadId: 'default',
    parentId: null,
    branchId: 'main',
    parts: [{ type: 'text', text: 'hi' }],
    attachments: [],
    ...overrides
  }
}

describe('convertMessage', () => {
  it('carries text through as a text part', () => {
    const converted = convertMessage(message({ content: 'hello', parts: [{ type: 'text', text: 'hello' }] }))

    expect(converted.role).toBe('user')
    expect(converted.content).toEqual([{ type: 'text', text: 'hello' }])
    expect(converted.id).toBe('1')
  })

  it('puts reasoning ahead of the answer', () => {
    const converted = convertMessage(
      message({
        role: 'assistant',
        meta: { reasoning: 'weighing it up' },
        parts: [{ type: 'text', text: 'the answer' }]
      })
    )

    expect(converted.content.map((part) => part.type)).toEqual(['reasoning', 'text'])
  })

  it('renders a widget as a tool call so the SDK draws it as generative UI', () => {
    const converted = convertMessage(
      message({
        role: 'assistant',
        parts: [
          {
            type: 'widget',
            id: 'w1',
            version: 1,
            kind: 'table',
            title: 'Rows',
            status: 'complete',
            data: { columns: ['a'], rows: [['1']] }
          }
        ]
      })
    )

    const [part] = converted.content
    expect(part).toMatchObject({
      type: 'tool-call',
      toolCallId: 'w1',
      toolName: WIDGET_TOOL,
      args: { kind: 'table', title: 'Rows' }
    })
  })

  it('marks a widget the Gateway reported as failed', () => {
    const converted = convertMessage(
      message({
        role: 'assistant',
        parts: [
          {
            type: 'widget',
            id: 'w2',
            version: 1,
            kind: 'status',
            title: 'Nope',
            status: 'error',
            data: {}
          }
        ]
      })
    )

    expect(converted.content[0]).toMatchObject({ isError: true })
  })

  it('leaves an unanswered question without a result so it reads as waiting', () => {
    const converted = convertMessage(
      message({
        role: 'assistant',
        parts: [{ type: 'ask', id: 'q1', kind: 'clarify', question: 'Which?', choices: ['a', 'b'] }]
      })
    )

    const [part] = converted.content
    expect(part).toMatchObject({ type: 'tool-call', toolCallId: 'q1', toolName: ASK_TOOL })
    expect(part).not.toHaveProperty('result')
  })

  it('gives an answered question a result so the card settles', () => {
    const converted = convertMessage(
      message({
        role: 'assistant',
        parts: [{ type: 'ask', id: 'q2', kind: 'clarify', question: 'Which?', answered: true }]
      })
    )

    expect(converted.content[0]).toMatchObject({ result: { answered: true } })
  })

  it('never leaks a secret name as an answer', () => {
    const converted = convertMessage(
      message({
        role: 'assistant',
        parts: [{ type: 'ask', id: 'q3', kind: 'secret', name: 'SMTP_PASSWORD', why: 'to send' }]
      })
    )

    expect(JSON.stringify(converted)).not.toContain('password')
    expect(converted.content[0]).toMatchObject({ args: { kind: 'secret', name: 'SMTP_PASSWORD' } })
  })

  it('renders an error row as an assistant message carrying the error', () => {
    const converted = convertMessage(
      message({ role: 'error', content: 'the provider refused', parts: [] })
    )

    expect(converted.role).toBe('assistant')
    expect(converted.status).toEqual({
      type: 'incomplete',
      reason: 'error',
      error: 'the provider refused'
    })
  })

  it('marks a streaming reply as running', () => {
    const converted = convertMessage(message({ role: 'assistant', meta: { streaming: true } }))

    expect(converted.status).toEqual({ type: 'running' })
  })

  it('keeps a mid-stream reply in the list even with nothing in it yet', () => {
    // Dropping it would make the working indicator flicker in and out on every
    // delta, because the row it hangs from would keep disappearing.
    const converted = convertMessage(
      message({ role: 'assistant', content: '', parts: [], meta: { streaming: true } })
    )

    expect(converted.content).toEqual([])
    expect(converted.status).toEqual({ type: 'running' })
  })

  it('moves attachments off the content and onto the message', () => {
    const converted = convertMessage(
      message({
        parts: [
          { type: 'text', text: 'see this' },
          { type: 'attachment', attachment_id: 'a1', name: 'notes.md', media_type: 'text/markdown', size: 12 }
        ],
        attachments: [
          {
            id: 'a1',
            thread_id: 'default',
            message_id: null,
            name: 'notes.md',
            media_type: 'text/markdown',
            size: 12,
            kind: 'document',
            created_at: at
          }
        ]
      })
    )

    expect(converted.content.map((part) => part.type)).toEqual(['text'])
    expect(converted.attachments?.[0]).toMatchObject({ id: 'a1', name: 'notes.md' })
  })

  it('gives parts stable ids so a card does not remount mid-stream', () => {
    const source = message({
      role: 'assistant',
      parts: [{ type: 'tool', name: 'web_search', content: 'ok' }]
    })

    const first = convertMessage(source).content[0]
    const second = convertMessage(source).content[0]

    expect(first).toMatchObject({ toolCallId: '1:0' })
    expect(second).toEqual(first)
  })
})

describe('convertMessages', () => {
  it('hides tool rows, which exist for the model and not for the reader', () => {
    const rows = [
      message({ id: 1, role: 'user' }),
      message({ id: 2, role: 'tool', content: 'raw tool output' }),
      message({ id: 3, role: 'assistant' })
    ]

    expect(rows.filter(isRenderable).map((row) => row.id)).toEqual([1, 3])
    expect(convertMessages(rows).map((row) => row.id)).toEqual(['1', '3'])
  })
})
