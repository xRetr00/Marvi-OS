import { describe, expect, it } from 'vitest'

import { parseBlocks, parseInline } from './markdown'

describe('parseBlocks', () => {
  it('treats plain text as a single paragraph', () => {
    expect(parseBlocks('hello')).toEqual([{ kind: 'paragraph', text: 'hello' }])
  })

  it('splits fenced code from prose', () => {
    expect(parseBlocks('before\n```ts\nconst x = 1\n```\nafter')).toEqual([
      { kind: 'paragraph', text: 'before' },
      { kind: 'code', lang: 'ts', text: 'const x = 1' },
      { kind: 'paragraph', text: 'after' }
    ])
  })

  it('preserves line breaks inside a paragraph', () => {
    expect(parseBlocks('a\nb')).toEqual([{ kind: 'paragraph', text: 'a\nb' }])
  })

  it('treats an unterminated fence as code to the end', () => {
    expect(parseBlocks('a\n```ts\ncode')).toEqual([
      { kind: 'paragraph', text: 'a' },
      { kind: 'code', lang: 'ts', text: 'code' }
    ])
  })

  it('returns nothing for empty input', () => {
    expect(parseBlocks('')).toEqual([])
  })
})

describe('parseInline', () => {
  it('splits inline code from text', () => {
    expect(parseInline('use `npm ci` here')).toEqual([
      { type: 'text', value: 'use ' },
      { type: 'code', value: 'npm ci' },
      { type: 'text', value: ' here' }
    ])
  })

  it('leaves text without backticks untouched', () => {
    expect(parseInline('plain')).toEqual([{ type: 'text', value: 'plain' }])
  })

  it('handles multiple code spans', () => {
    expect(parseInline('`a` and `b`')).toEqual([
      { type: 'code', value: 'a' },
      { type: 'text', value: ' and ' },
      { type: 'code', value: 'b' }
    ])
  })
})
