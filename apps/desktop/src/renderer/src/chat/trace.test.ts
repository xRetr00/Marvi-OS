import { describe, expect, it } from 'vitest'

import type { ChatPart } from '../../../shared/runtime'
import { answerText, foldEvent } from './trace'

/** Feed a whole stream through, as the hook does. */
function run(events: Array<Record<string, unknown>>): ChatPart[] {
  return events.reduce<ChatPart[]>(foldEvent, [])
}

describe('foldEvent', () => {
  it('keeps a turn in the order it happened', () => {
    // The shape of a real tool-using turn: think, say something, call a tool,
    // think again, answer. It used to collapse to "thinking" + "answer".
    const parts = run([
      { reasoning: 'The user wants ' },
      { reasoning: 'the room state.' },
      { delta: 'Let me ' },
      { delta: 'check.' },
      { tool_call: { id: 'c1', name: 'room_state', arguments: { detail: true } } },
      { tool_result: { id: 'c1', content: 'light: off', status: 'complete' } },
      { reasoning: 'The light is off.' },
      { delta: 'The light ' },
      { delta: 'is off.' }
    ])

    expect(parts.map((part) => part.type)).toEqual([
      'reasoning',
      'commentary',
      'tool',
      'reasoning',
      'text'
    ])
  })

  it('merges consecutive chunks into one part', () => {
    const parts = run([{ reasoning: 'a' }, { reasoning: 'b' }, { delta: 'c' }, { delta: 'd' }])

    expect(parts).toEqual([
      { type: 'reasoning', text: 'ab' },
      { type: 'text', text: 'cd' }
    ])
  })

  it('reclassifies text that preceded a tool call as commentary', () => {
    const parts = run([
      { delta: 'Let me check.' },
      { tool_call: { id: 'c1', name: 'room_state', arguments: {} } }
    ])

    expect(parts[0]).toEqual({ type: 'commentary', text: 'Let me check.' })
  })

  it('drops whitespace-only text rather than keeping empty commentary', () => {
    const parts = run([{ delta: '  \n' }, { tool_call: { id: 'c1', name: 'x', arguments: {} } }])

    expect(parts.map((part) => part.type)).toEqual(['tool'])
  })

  it('shows a call as running until its result arrives', () => {
    const running = run([{ tool_call: { id: 'c1', name: 'file_read', arguments: { path: 'a' } } }])
    expect(running[0]).toMatchObject({ type: 'tool', status: 'running', arguments: { path: 'a' } })

    const done = foldEvent(running, { tool_result: { id: 'c1', content: 'hello', status: 'complete' } })
    expect(done[0]).toMatchObject({ status: 'complete', content: 'hello' })
  })

  it('matches results to calls by id when several run', () => {
    const parts = run([
      { tool_call: { id: 'a', name: 'file_read', arguments: {} } },
      { tool_call: { id: 'b', name: 'web_search', arguments: {} } },
      { tool_result: { id: 'b', content: 'found', status: 'complete' } }
    ])

    expect(parts[0]).toMatchObject({ id: 'a', status: 'running' })
    expect(parts[1]).toMatchObject({ id: 'b', status: 'complete', content: 'found' })
  })

  it('records a failed call as failed', () => {
    const parts = run([
      { tool_call: { id: 'c1', name: 'room_state', arguments: {} } },
      { tool_result: { id: 'c1', content: 'offline', status: 'failed' } }
    ])

    expect(parts[0]).toMatchObject({ status: 'failed' })
  })

  it('leaves the parts alone for an event it does not know', () => {
    const before = run([{ delta: 'hi' }])
    expect(foldEvent(before, { something_new: true })).toBe(before)
    // The legacy name-only event is superseded by `tool_call`.
    expect(foldEvent(before, { tool: 'room_state' })).toBe(before)
  })
})

describe('answerText', () => {
  it('is the answer only, never the commentary before it', () => {
    const parts = run([
      { delta: 'Let me check.' },
      { tool_call: { id: 'c1', name: 'room_state', arguments: {} } },
      { delta: 'The light is off.' }
    ])

    expect(answerText(parts)).toBe('The light is off.')
  })
})
