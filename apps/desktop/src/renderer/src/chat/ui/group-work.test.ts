import { describe, expect, it } from 'vitest'
import type { PartState } from '@assistant-ui/react'

import { ASK_TOOL, WIDGET_TOOL } from '../runtime/convert'
import { formatWorked, groupWork } from './group-work'

const part = (value: Record<string, unknown>): PartState => value as unknown as PartState

describe('groupWork', () => {
  it('gathers thoughts, commentary and ordinary tool calls into the work', () => {
    expect(groupWork(part({ type: 'reasoning', text: 'x' }))).toEqual(['group-work'])
    expect(groupWork(part({ type: 'data', name: 'commentary', data: {} }))).toEqual(['group-work'])
    expect(groupWork(part({ type: 'tool-call', toolName: 'file_read' }))).toEqual(['group-work'])
  })

  it('leaves the answer outside', () => {
    expect(groupWork(part({ type: 'text', text: 'the answer' }))).toBeNull()
    expect(groupWork(part({ type: 'source' }))).toBeNull()
  })

  it('never folds away a widget or a question card', () => {
    // A widget inside the work log is a widget nobody sees; a question card
    // inside it is a turn blocked on something invisible.
    expect(groupWork(part({ type: 'tool-call', toolName: WIDGET_TOOL }))).toBeNull()
    expect(groupWork(part({ type: 'tool-call', toolName: ASK_TOOL }))).toBeNull()
  })

  it('ignores data parts that are not commentary', () => {
    expect(groupWork(part({ type: 'data', name: 'something-else', data: {} }))).toBeNull()
  })
})

describe('formatWorked', () => {
  it('reads at a glance', () => {
    expect(formatWorked(400)).toBe('0s')
    expect(formatWorked(12_000)).toBe('12s')
    expect(formatWorked(65_000)).toBe('1m 5s')
    expect(formatWorked(120_000)).toBe('2m')
  })
})
