import type { ComponentPropsWithoutRef } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import 'katex/dist/katex.min.css'

import { CopyMessageAction } from './components/MessageAction'
import { normalizeMathDelimiters } from './math'

export function Markdown({ content }: { content: string }): React.JSX.Element | null {
  if (!content.trim()) return null
  const markdown = normalizeMathDelimiters(content)
  return (
    <div className="chat-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        skipHtml
        components={{
          a: SafeLink,
          blockquote: ({ children }) => <blockquote className="chat-quote">{children}</blockquote>,
          code: Code,
          h1: ({ children }) => <h1 className="chat-md-h1">{children}</h1>,
          h2: ({ children }) => <h2 className="chat-md-h2">{children}</h2>,
          h3: ({ children }) => <h3 className="chat-md-h3">{children}</h3>,
          hr: () => <hr className="chat-md-rule" />,
          table: ({ children }) => (
            <div className="chat-table-scroll">
              <table>{children}</table>
            </div>
          ),
          input: ({ type, ...props }) =>
            type === 'checkbox' ? <input type="checkbox" disabled {...props} /> : null,
          pre: ({ children }) => <pre className="chat-code">{children}</pre>
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  )
}

function SafeLink({ href, children, ...props }: ComponentPropsWithoutRef<'a'>): React.JSX.Element {
  const external = typeof href === 'string' && /^https?:\/\//i.test(href)
  return (
    <a
      {...props}
      href={external ? href : undefined}
      rel="noreferrer noopener"
      target={external ? '_blank' : undefined}
    >
      {children}
    </a>
  )
}

function Code({
  className,
  children,
  ...props
}: ComponentPropsWithoutRef<'code'>): React.JSX.Element {
  const text = String(children).replace(/\n$/, '')
  const language = /language-([^\s]+)/.exec(className ?? '')?.[1]
  const block = Boolean(language) || text.includes('\n')
  if (!block) {
    return (
      <code className="chat-inline-code" {...props}>
        {children}
      </code>
    )
  }
  return (
    <span className="chat-code-shell">
      <span className="chat-code-head">
        <span>{language || 'plain text'}</span>
        <CopyMessageAction content={text} label="Copy code" />
      </span>
      <code className={className} {...props}>
        {text}
      </code>
    </span>
  )
}
