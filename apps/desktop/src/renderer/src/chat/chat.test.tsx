import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import { Markdown } from './MarkdownView'
import { contextMeterCells, contextPercent, contextSegments } from './context-breakdown'
import { Sessions } from './components/Sessions'

const at = '2026-08-17T14:05:00Z'
const chatCss = readFileSync(join(__dirname, 'chat.css'), 'utf8').replace(/\r\n/g, '\n')

describe('transcript visual contract', () => {
  it('keeps responses unboxed and work evidence subordinate', () => {
    const transcript = chatCss.slice(chatCss.lastIndexOf('/* Transcript hierarchy'))
    expect(transcript).toContain('.chat-user {')
    expect(transcript).toContain('.chat-assistant {')
    expect(transcript).not.toMatch(/\.chat-assistant\s*\{[^}]*border:/s)
    expect(transcript).toContain('.chat-scaffold {')
    expect(transcript).toContain('opacity: 0.67')
    expect(transcript).toContain('.chat-reasoning-body.is-live')
    expect(transcript).toContain('max-height: min(84px, 14vh)')
    expect(transcript).toContain('.chat-reasoning + .chat-inline-tool')
    expect(transcript).toContain('font-size: 8.5px')
  })
})

describe('contextSegments', () => {
  it('reports an unmeasured window as unknown rather than as empty', () => {
    const context = {
      input_tokens: 0,
      cached_tokens: 0,
      context_window: 8000,
      reply_reserve: 1024,
      messages: 0,
      files: 0,
      sources: 0,
      provider: 'openai',
      model: 'gpt-test'
    }

    // The Gateway reports only what a provider actually sent. Zero means
    // "nobody said", not "the window is empty", and a conversation eight turns
    // deep was reading as untouched.
    expect(contextPercent(context)).toBeNull()
    expect(contextSegments(context)).toEqual([])
  })

  it('breaks a measured window down into its four parts', () => {
    const context = {
      input_tokens: 2000,
      cached_tokens: 500,
      context_window: 8000,
      reply_reserve: 1024,
      messages: 4,
      files: 0,
      sources: 0,
      provider: 'openai',
      model: 'gpt-test'
    }

    expect(contextPercent(context)).toBe(25)
    expect(contextSegments(context)).toEqual([
      { id: 'prompt', label: 'Prompt', tokens: 1500 },
      { id: 'cached', label: 'Cached', tokens: 500 },
      { id: 'reserve', label: 'Reply reserve', tokens: 1024 },
      { id: 'available', label: 'Available', tokens: 4976 }
    ])
  })

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
    expect(
      contextMeterCells({
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
    ).toHaveLength(12)
  })

  it('reports unusable provider counters as unknown, not as a percentage', () => {
    // NaN in, no number out. Clamping it to 0 produced a confident "0%" from
    // a counter that was broken.
    expect(
      contextPercent({
        input_tokens: Number.NaN,
        cached_tokens: -20,
        context_window: 8000,
        reply_reserve: 1024,
        messages: 0,
        files: 0,
        sources: 0,
        provider: 'openai',
        model: 'gpt-test'
      })
    ).toBeNull()
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

  it('groups Telegram conversations under their own logo', () => {
    const thread = {
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
    const html = renderToStaticMarkup(
      <Sessions
        sessions={[
          { ...thread, id: 'a', title: 'Desk thread' },
          { ...thread, id: 'b', title: 'Sam', channel: 'telegram' }
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
        timing={null}
      />
    )
    const [recent, group] = html.split('aria-label="Telegram conversations"')
    expect(recent).toContain('Desk thread')
    expect(recent).not.toContain('>Sam<')
    expect(group).toContain('TELEGRAM')
    expect(group).toContain('>Sam<')
    expect(group).toContain('chat-session-logo')
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
