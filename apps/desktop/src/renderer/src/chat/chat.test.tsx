import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { Markdown } from './MarkdownView'
import type { ChatMessage } from './types'
import { AgentMessage } from './components/AgentMessage'
import { Composer } from './components/Composer'
import { MessageList } from './components/MessageList'
import { Sessions } from './components/Sessions'
import { ToolMessage } from './components/ToolMessage'
import { UserMessage } from './components/UserMessage'

const at = '2026-08-17T14:05:00Z'

function message(overrides: Partial<ChatMessage>): ChatMessage {
  return { id: 1, at, role: 'user', content: 'hi', meta: {}, ...overrides }
}

describe('UserMessage', () => {
  it('labels the turn YOU and renders the text', () => {
    const html = renderToStaticMarkup(<UserMessage message={message({ content: 'hello' })} />)
    expect(html).toContain('YOU')
    expect(html).toContain('hello')
  })
})

describe('AgentMessage', () => {
  it('labels MARVI and renders inline code and metadata', () => {
    const html = renderToStaticMarkup(
      <AgentMessage
        message={message({
          role: 'assistant',
          content: 'use `npm ci`',
          meta: { provider: 'openai', tokens: 12 }
        })}
      />
    )
    expect(html).toContain('MARVI')
    expect(html).toContain('chat-inline-code')
    expect(html).toContain('npm ci')
    expect(html).toContain('openai')
    expect(html).toContain('12 tok')
  })
})

describe('ToolMessage', () => {
  it('labels the tool and stays collapsed by default', () => {
    const html = renderToStaticMarkup(
      <ToolMessage
        message={message({ role: 'tool', content: 'secret result', meta: { tool: 'file_read' } })}
      />
    )
    expect(html).toContain('FILE_READ')
    expect(html).not.toContain('secret result')
  })
})

describe('Composer', () => {
  const noop = (): void => {}

  it('disables send when there is nothing to send', () => {
    const html = renderToStaticMarkup(
      <Composer draft="" busy={false} available onDraftChange={noop} onSend={noop} />
    )
    // Send is a control on the edge of the field now, not a full-width button
    // competing with the transcript for attention.
    expect(html).toContain('aria-label="Send"')
    expect(html).toContain('disabled')
  })

  it('says how to send, since Enter and Shift+Enter differ', () => {
    const html = renderToStaticMarkup(
      <Composer draft="hello" busy={false} available onDraftChange={noop} onSend={noop} />
    )
    expect(html).toContain('Enter sends')
    expect(html).toContain('chat-compose-beam')
    expect(html).toContain('// MESSAGE')
  })

  it('offers a hint to connect a provider when unavailable', () => {
    const html = renderToStaticMarkup(
      <Composer draft="" busy={false} available={false} onDraftChange={noop} onSend={noop} />
    )
    expect(html).toContain('Connect a provider')
  })

  it('keeps cancellation available while a reply is streaming', () => {
    const html = renderToStaticMarkup(
      <Composer
        draft=""
        busy
        available
        onDraftChange={noop}
        onSend={noop}
        onCancel={noop}
      />
    )
    expect(html).toContain('aria-label="Stop"')
    expect(html).toContain('RECEIVING')
  })
})

describe('MessageList', () => {
  it('renders an empty state when there are no messages', () => {
    const html = renderToStaticMarkup(<MessageList messages={[]} busy={false} />)
    expect(html).toContain('chat-empty')
  })

  it('renders each message by role', () => {
    const html = renderToStaticMarkup(
      <MessageList
        messages={[message({ role: 'user' }), message({ id: 2, role: 'assistant' })]}
        busy={false}
      />
    )
    expect(html).toContain('YOU')
    expect(html).toContain('MARVI')
  })
})

describe('Sessions', () => {
  it('renders session titles and a new button', () => {
    const html = renderToStaticMarkup(
      <Sessions
        sessions={[{ id: 'a', title: 'Hi there', updatedAt: '2m ago', messageCount: 3 }]}
        activeId="a"
        onSelect={() => {}}
        onNew={() => {}}
      />
    )
    expect(html).toContain('Hi there')
    expect(html).toContain('NEW')
    expect(html).toContain('3 msgs')
  })
})

describe('Markdown', () => {
  it('renders fenced code as a block', () => {
    const html = renderToStaticMarkup(<Markdown content={'before\n```js\n1 + 1\n```\nafter'} />)
    expect(html).toContain('chat-code')
    expect(html).toContain('1 + 1')
    expect(html).toContain('before')
    expect(html).toContain('after')
  })
})
