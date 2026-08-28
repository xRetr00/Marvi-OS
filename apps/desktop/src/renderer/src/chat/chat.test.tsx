import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { Markdown } from './MarkdownView'
import { contextSegments } from './context-breakdown'
import type { ChatMessage } from './types'
import { AgentMessage } from './components/AgentMessage'
import { Composer } from './components/Composer'
import { MessageList } from './components/MessageList'
import { Sessions } from './components/Sessions'
import { ToolMessage } from './components/ToolMessage'
import { UserMessage } from './components/UserMessage'

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

describe('UserMessage', () => {
  it('keeps the sender label accessible without a visible turn header', () => {
    const html = renderToStaticMarkup(<UserMessage message={message({ content: 'hello' })} />)
    expect(html).toContain('<span class="sr-only">YOU</span>')
    expect(html).toContain('hello')
    expect(html).not.toContain('chat-turn-head')
  })
})

describe('AgentMessage', () => {
  it('keeps Marvi accessible and renders a headerless compact response', () => {
    const html = renderToStaticMarkup(
      <AgentMessage
        message={message({
          role: 'assistant',
          content: 'use `npm ci`',
          meta: { provider: 'openai', tokens: 12 }
        })}
      />
    )
    expect(html).toContain('<span class="sr-only">MARVI</span>')
    expect(html).toContain('chat-inline-code')
    expect(html).toContain('npm ci')
    expect(html).not.toContain('chat-turn-head')
    expect(html).not.toContain('openai')
    expect(html).not.toContain('12 tok')
  })

  it('renders persisted source widgets as usable evidence cards', () => {
    const html = renderToStaticMarkup(
      <AgentMessage
        message={message({
          role: 'assistant',
          content: 'Found it.',
          parts: [
            { type: 'text', text: 'Found it.' },
            {
              type: 'widget',
              id: 'sources-1',
              version: 1,
              kind: 'sources',
              title: 'Web evidence',
              status: 'complete',
              data: {
                items: [
                  {
                    title: 'Official result',
                    url: 'https://example.com/result',
                    snippet: 'Evidence'
                  }
                ]
              }
            }
          ]
        })}
      />
    )
    expect(html).toContain('Sources')
    expect(html).not.toContain('Web evidence')
    expect(html).toContain('Official result')
    expect(html).toContain('https://example.com/result')
    expect(html).toContain('class="chat-sources"')
    expect(html).not.toContain('SOURCES</span>')
  })

  it('renders comparisons as compact option fields without a widget-type banner', () => {
    const html = renderToStaticMarkup(
      <AgentMessage
        message={message({
          role: 'assistant',
          content: 'Option A is the better fit.',
          parts: [
            {
              type: 'widget',
              id: 'comparison-1',
              version: 1,
              kind: 'comparison',
              title: 'Candidate comparison',
              status: 'complete',
              data: {
                items: [
                  { label: 'Option A', value: 'Recommended', detail: 'Lower latency' },
                  { label: 'Option B', value: 'Fallback', detail: 'Higher cost' }
                ]
              }
            }
          ]
        })}
      />
    )
    expect(html).toContain('chat-comparison-options')
    expect(html).toContain('recommended')
    expect(html).not.toContain('>COMPARISON<')
  })
})

describe('ToolMessage', () => {
  it('labels the tool and stays collapsed by default', () => {
    const html = renderToStaticMarkup(
      <ToolMessage
        message={message({ role: 'tool', content: 'secret result', meta: { tool: 'file_read' } })}
      />
    )
    expect(html).toContain('File read')
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

  it('uses a compact Assistant UI-style input surface', () => {
    const html = renderToStaticMarkup(
      <Composer draft="hello" busy={false} available onDraftChange={noop} onSend={noop} />
    )
    expect(html).toContain('chat-compose-field')
    expect(html).toContain('data-active="true"')
    expect(html).not.toContain('// MESSAGE')
  })

  it('offers a hint to connect a provider when unavailable', () => {
    const html = renderToStaticMarkup(
      <Composer draft="" busy={false} available={false} onDraftChange={noop} onSend={noop} />
    )
    expect(html).toContain('Connect a provider')
  })

  it('keeps cancellation available while a reply is streaming', () => {
    const html = renderToStaticMarkup(
      <Composer draft="" busy available onDraftChange={noop} onSend={noop} onCancel={noop} />
    )
    expect(html).toContain('aria-label="Stop"')
    expect(html).toContain('is-stop')
    expect(html).not.toContain('textarea disabled')
  })

  it('shows provider-reported context instead of draft-length guesses', () => {
    const html = renderToStaticMarkup(
      <Composer
        draft="hello"
        busy={false}
        available
        onDraftChange={noop}
        onSend={noop}
        context={{
          input_tokens: 2000,
          cached_tokens: 800,
          context_window: 8000,
          reply_reserve: 1024,
          messages: 6,
          files: 1,
          sources: 3,
          provider: 'openai',
          model: 'gpt-test'
        }}
      />
    )
    expect(html).toContain('25')
    expect(html).toContain('2k / 8k')
    expect(html).toContain('Prompt')
    expect(html).toContain('Cached')
    expect(html).toContain('Reply reserve')
    expect(html).toContain('Available')
    expect(html).not.toContain('chars')
  })
})

describe('contextSegments', () => {
  it('splits only provider-reported token facts and preserves the whole window', () => {
    const segments = contextSegments({
      input_tokens: 2000,
      cached_tokens: 800,
      context_window: 8000,
      reply_reserve: 1024,
      messages: 6,
      files: 1,
      sources: 3,
      provider: 'openai',
      model: 'gpt-test'
    })

    expect(segments).toEqual([
      { id: 'prompt', label: 'Prompt', tokens: 1200 },
      { id: 'cached', label: 'Cached', tokens: 800 },
      { id: 'reserve', label: 'Reply reserve', tokens: 1024 },
      { id: 'available', label: 'Available', tokens: 4976 }
    ])
    expect(segments.reduce((sum, segment) => sum + segment.tokens, 0)).toBe(8000)
  })
})

describe('MessageList', () => {
  it('renders an empty state when there are no messages', () => {
    const html = renderToStaticMarkup(
      <MessageList messages={[]} busy={false} onSuggestion={() => {}} />
    )
    expect(html).toContain('chat-empty')
    expect(html).toContain('Starter prompts')
    expect(html).toContain('What is happening in the room right now?')
  })

  it('renders each message by role', () => {
    const html = renderToStaticMarkup(
      <MessageList
        messages={[message({ role: 'user' }), message({ id: 2, role: 'assistant' })]}
        busy={false}
        onSuggestion={() => {}}
      />
    )
    expect(html).toContain('YOU')
    expect(html).toContain('MARVI')
  })

  it('uses one working row until the optimistic reply starts streaming', () => {
    const html = renderToStaticMarkup(
      <MessageList
        messages={[
          message({ role: 'user' }),
          message({ id: -2, role: 'assistant', content: '', meta: { streaming: true } })
        ]}
        busy
        onSuggestion={() => {}}
      />
    )
    expect(html.match(/MARVI/g)).toHaveLength(1)
    expect(html).toContain('WORKING')
  })
})

describe('Sessions', () => {
  it('renders session titles and a new button', () => {
    const html = renderToStaticMarkup(
      <Sessions
        sessions={[
          {
            id: 'a',
            title: 'Hi there',
            created_at: at,
            updated_at: at,
            archived: false,
            active_message_id: 3,
            active_branch: 'main',
            selected_provider: '',
            selected_model: '',
            selected_effort: '',
            message_count: 3
          }
        ]}
        activeId="a"
        onSelect={() => {}}
        onNew={() => {}}
        onRename={() => {}}
        onArchive={() => {}}
        onDelete={() => {}}
        onExit={() => {}}
        onExport={() => {}}
        exportDisabled={false}
        timing={<span>SESSION 00:12</span>}
      />
    )
    expect(html).toContain('Hi there')
    expect(html).toContain('NEW CHAT')
    expect(html).toContain('3 msgs')
    expect(html).toContain('Search conversations')
    expect(html).toContain('CONTROL CENTER')
    expect(html).toContain('SESSION 00:12')
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

  it('renders GFM tables, tasks, links, and math without raw HTML', () => {
    const html = renderToStaticMarkup(
      <Markdown
        content={
          '| A | B |\n| - | - |\n| 1 | 2 |\n\n- [x] done\n\n[x](https://example.com)\n\n$E=mc^2$\n\n<script>bad()</script>'
        }
      />
    )
    expect(html).toContain('chat-table-scroll')
    expect(html).toContain('type="checkbox"')
    expect(html).toContain('noreferrer noopener')
    expect(html).toContain('katex')
    expect(html).not.toContain('<script>')
  })

  it('renders common parenthesized and bracketed LaTeX delimiters', () => {
    const html = renderToStaticMarkup(<Markdown content={'\\(n^2\\)\n\n\\[E=mc^2\\]'} />)

    expect(html.match(/class="katex"/g)).toHaveLength(2)
  })
})
